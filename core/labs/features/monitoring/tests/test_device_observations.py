"""PostgreSQL behavior tests for scoped, ordered device connection observations."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier, Event
from uuid import uuid4

import pytest
from django.db import close_old_connections
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from core.common.contracts import ActorContext
from core.common.domain.errors import ValidationFailed
from core.labs.features.monitoring.api.connections import DeviceConnectionSerializer
from core.labs.features.monitoring.application.observe_devices import (
    InvalidateDeviceConnectionsInput,
    invalidate_device_connections,
)
from core.labs.features.monitoring.application.observe_devices import (
    observe_devices as execute_observations,
)
from core.labs.features.monitoring.contracts import DeviceObservation, DeviceObservationInput
from core.labs.features.monitoring.exceptions import ObservationConflict, ObservationInProgress, ObservationKeyReuse
from core.labs.features.monitoring.queries.connections import list_device_connections
from core.labs.models import Equipment
from core.labs.models.monitoring import (
    DeviceConnection,
    DeviceObservationBatch,
    DeviceObservationCursor,
    MonitoringEvent,
)
from core.labs.models.resource.equipment import EquipmentInterface
from tests.factories import ComputingEquipmentFactory


def observe_devices(command):
    actor = ActorContext(
        command.agent_key, "system", frozenset({"monitoring:report"}), frozenset({command.computer_id})
    )
    return execute_observations(command, actor=actor)


pytestmark = pytest.mark.django_db


@pytest.fixture
def computer():
    return ComputingEquipmentFactory()


@pytest.fixture
def command(computer):
    return DeviceObservationInput(
        computer_id=computer.pk,
        agent_key=str(uuid4()),
        generation_key=uuid4(),
        batch_key=uuid4(),
        collector_key="usb",
        sequence=1,
        collected_at=timezone.now(),
        is_complete=True,
        devices=(DeviceObservation("usb-port-1", "USB", "connected", "Instrument", "SERIAL-1"),),
    )


def next_report(command, **changes):
    return replace(command, sequence=command.sequence + 1, batch_key=uuid4(), **changes)


def test_complete_snapshot_matches_serial_and_declared_interface_without_changing_inventory(command, computer):
    interface = EquipmentInterface.objects.create(name="USB")
    peripheral = Equipment.objects.create(sku="DEVICE-1", name="Scope", serial_number="SERIAL-1", kind=computer.kind)
    peripheral.interfaces.add(interface)

    ack = observe_devices(command)

    connection = DeviceConnection.objects.get()
    assert ack.disposition == "applied" and not ack.is_replayed
    assert (connection.computer_id, connection.equipment_id, connection.interface_id) == (
        computer.pk,
        peripheral.pk,
        interface.pk,
    )
    assert connection.match_status == "matched" and connection.state == "connected"
    assert connection.received_at == ack.received_at
    peripheral.refresh_from_db()
    assert peripheral.serial_number == "SERIAL-1"
    event = MonitoringEvent.objects.get()
    assert event.computer_id == computer.pk and event.payload["devices"][0]["observation_key"] == "usb-port-1"


def test_detach_without_serial_preserves_identity_but_reconnect_without_serial_does_not(command, computer):
    interface = EquipmentInterface.objects.create(name="USB")
    peripheral = Equipment.objects.create(sku="DETACH-1", name="Probe", serial_number="SERIAL-1", kind=computer.kind)
    peripheral.interfaces.add(interface)
    observe_devices(command)
    detached = replace(command.devices[0], state="disconnected", serial_number="", name="")
    observe_devices(next_report(command, devices=(detached,), is_complete=False))
    connection = DeviceConnection.objects.get()
    assert connection.state == "disconnected" and connection.equipment_id == peripheral.pk
    assert connection.serial_number == "SERIAL-1" and connection.name == "Instrument"
    observe_devices(replace(command, batch_key=uuid4(), sequence=3, devices=(replace(detached, state="connected"),)))
    connection.refresh_from_db()
    assert connection.state == "connected" and connection.match_status == "unmatched"
    assert connection.equipment_id is None and connection.serial_number == ""


def test_casefold_colliding_interface_references_are_ambiguous(command, computer):
    peripheral = Equipment.objects.create(sku="CASE-1", name="Probe", serial_number="SERIAL-1", kind=computer.kind)
    peripheral.interfaces.add(
        EquipmentInterface.objects.create(name="USB"), EquipmentInterface.objects.create(name="usb")
    )
    observe_devices(command)
    assert DeviceConnection.objects.get().match_status == "ambiguous"


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("unknown", "unmatched"),
        ("blank_serial", "unmatched"),
        ("wrong_interface", "interface_mismatch"),
        ("duplicate_serial", "ambiguous"),
    ],
)
def test_matching_keeps_unknown_incompatible_and_ambiguous_devices_unresolved(command, computer, scenario, expected):
    if scenario != "unknown" and scenario != "blank_serial":
        interface = EquipmentInterface.objects.create(name="USB" if scenario == "duplicate_serial" else "Ethernet")
        count = 2 if scenario == "duplicate_serial" else 1
        for index in range(count):
            equipment = Equipment.objects.create(
                sku=f"DUP-{index}", name="Same serial", serial_number="SERIAL-1", kind=computer.kind
            )
            equipment.interfaces.add(interface)
    if scenario == "blank_serial":
        command = replace(command, devices=(replace(command.devices[0], serial_number=""),))
    observe_devices(command)
    connection = DeviceConnection.objects.get()
    assert connection.match_status == expected
    assert connection.equipment_id is None and connection.interface_id is None


def test_exact_replay_preserves_ack_event_count_and_freshness_and_changed_content_is_rejected(command):
    original = observe_devices(command)
    with freeze_time(timezone.now() + timedelta(minutes=3)):
        replay = observe_devices(command)
        assert replay.is_replayed
        assert replace(replay, is_replayed=False) == original
        assert list_device_connections(computer_id=command.computer_id).get().freshness == "stale"
    with pytest.raises(ObservationKeyReuse) as error:
        observe_devices(replace(command, devices=(replace(command.devices[0], name="Changed"),)))
    assert error.value.code == "idempotency_key_reuse"
    assert DeviceObservationBatch.objects.count() == 1
    assert MonitoringEvent.objects.count() == 1
    assert DeviceConnection.objects.get().received_at == original.received_at


def test_out_of_order_batch_is_acknowledged_without_overwriting_projection_and_sequence_reuse_conflicts(command):
    observe_devices(replace(command, sequence=5))
    original = DeviceConnection.objects.get()
    stale = observe_devices(replace(command, sequence=3, batch_key=uuid4(), devices=()))
    assert stale.disposition == "stale"
    current = DeviceConnection.objects.get()
    assert current.state == "connected" and current.sequence == 5
    assert current.received_at == original.received_at
    assert MonitoringEvent.objects.count() == 1
    with pytest.raises(ObservationConflict):
        observe_devices(replace(command, sequence=5, batch_key=uuid4()))
    assert DeviceObservationBatch.objects.count() == 2


def test_partial_snapshot_never_disconnects_omissions_and_full_reconciliation_stays_in_collector_scope(command):
    second_device = DeviceObservation("usb-port-2", "USB", "connected", "Second", "SERIAL-2")
    observe_devices(replace(command, devices=(*command.devices, second_device)))
    observe_devices(replace(command, batch_key=uuid4(), collector_key="network"))
    observe_devices(next_report(command, is_complete=False, devices=()))
    assert DeviceConnection.objects.filter(state="connected").count() == 3
    observe_devices(replace(command, sequence=3, batch_key=uuid4(), devices=()))
    assert DeviceConnection.objects.filter(collector_key="usb", state="disconnected").count() == 2
    assert DeviceConnection.objects.get(collector_key="network").state == "connected"


def test_partial_snapshot_cannot_grow_active_inventory_beyond_the_collector_limit(command):
    devices = tuple(DeviceObservation(f"port-{index}", "USB", "connected") for index in range(200))
    observe_devices(replace(command, devices=devices))
    excess = next_report(command, is_complete=False, devices=(DeviceObservation("port-extra", "USB", "connected"),))
    with pytest.raises(ValidationFailed) as error:
        observe_devices(excess)
    assert error.value.code == "validation_failed"
    assert DeviceConnection.objects.filter(state="connected").count() == 200
    assert not DeviceConnection.objects.filter(observation_key="port-extra").exists()
    assert DeviceObservationBatch.objects.count() == 1
    assert MonitoringEvent.objects.count() == 1
    assert DeviceObservationCursor.objects.get().sequence == 1


def test_partial_snapshot_can_replace_a_detached_device_at_the_collector_limit(command):
    devices = tuple(DeviceObservation(f"port-{index}", "USB", "connected") for index in range(200))
    observe_devices(replace(command, devices=devices))
    replacement = next_report(
        command,
        is_complete=False,
        devices=(
            DeviceObservation("port-0", "USB", "disconnected"),
            DeviceObservation("port-replacement", "USB", "connected"),
        ),
    )
    result = observe_devices(replacement)
    assert result.disposition == "applied"
    assert DeviceConnection.objects.filter(state="connected").count() == 200
    assert DeviceConnection.objects.get(observation_key="port-0").state == "disconnected"
    assert DeviceConnection.objects.get(observation_key="port-replacement").state == "connected"
    assert DeviceObservationBatch.objects.count() == 2
    assert MonitoringEvent.objects.count() == 2


def test_repeated_full_snapshots_preserve_the_original_disconnect_observation(command):
    observe_devices(command)
    disconnected_at = command.collected_at + timedelta(minutes=1)
    with freeze_time(disconnected_at):
        observe_devices(next_report(command, devices=(), collected_at=disconnected_at))
    disconnected = DeviceConnection.objects.get()
    assert disconnected.state == "disconnected" and disconnected.sequence == 2
    later = disconnected_at + timedelta(minutes=1)
    with freeze_time(later):
        observe_devices(replace(command, sequence=3, batch_key=uuid4(), devices=(), collected_at=later))
    retained = DeviceConnection.objects.get()
    assert retained.received_at == disconnected.received_at
    assert retained.observed_at == disconnected.observed_at
    assert retained.sequence == 2
    assert DeviceObservationCursor.objects.get().sequence == 3
    assert MonitoringEvent.objects.count() == 3


def test_new_generation_requires_full_snapshot_and_reconciles_previous_connections(command):
    observe_devices(command)
    changed_generation = replace(command, generation_key=uuid4(), batch_key=uuid4(), devices=())
    with pytest.raises(ObservationConflict):
        observe_devices(replace(changed_generation, is_complete=False))
    assert DeviceObservationBatch.objects.count() == 1
    observe_devices(changed_generation)
    connection = DeviceConnection.objects.get()
    assert connection.state == "disconnected" and connection.generation_key == changed_generation.generation_key
    assert DeviceObservationCursor.objects.get().generation_key == changed_generation.generation_key


def test_invalidation_makes_state_unknown_and_requires_full_snapshot_even_for_same_generation(command):
    observe_devices(command)
    invalidate_device_connections(
        InvalidateDeviceConnectionsInput(command.computer_id),
        actor=ActorContext(
            command.agent_key, "system", frozenset({"monitoring:invalidate"}), frozenset({command.computer_id})
        ),
    )
    assert list_device_connections(computer_id=command.computer_id).get().freshness == "unknown"
    with pytest.raises(ObservationConflict):
        observe_devices(next_report(command, is_complete=False))
    observe_devices(next_report(command, devices=()))
    current = list_device_connections(computer_id=command.computer_id).get()
    assert current.freshness == "fresh" and current.state == "disconnected"


def test_freshness_considers_collection_time_as_well_as_server_receipt(command):
    old = replace(command, collected_at=timezone.now() - timedelta(minutes=5))
    observe_devices(old)
    assert list_device_connections(computer_id=command.computer_id).get().freshness == "stale"


@pytest.mark.parametrize(
    "change",
    [
        {"sequence": 0},
        {"sequence": 9007199254740992},
        {"collected_at": timezone.now() + timedelta(minutes=10)},
        {"devices": tuple(DeviceObservation(str(index), "USB", "connected") for index in range(201))},
        {
            "devices": (
                DeviceObservation("duplicate", "USB", "connected"),
                DeviceObservation("duplicate", "USB", "connected"),
            )
        },
    ],
)
def test_invalid_snapshot_is_rejected_before_any_persistent_writes(command, change):
    with pytest.raises(ValidationFailed):
        observe_devices(replace(command, **change))
    assert not DeviceConnection.objects.exists()
    assert not DeviceObservationBatch.objects.exists()
    assert not DeviceObservationCursor.objects.exists()
    assert not MonitoringEvent.objects.exists()


def test_event_storage_failure_rolls_back_batch_cursor_and_connections(command, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("Event storage unavailable")

    monkeypatch.setattr(MonitoringEvent.objects, "create", unavailable)
    with pytest.raises(RuntimeError, match="Event storage unavailable"):
        observe_devices(command)
    assert not DeviceConnection.objects.exists()
    assert not DeviceObservationBatch.objects.exists()
    assert not DeviceObservationCursor.objects.exists()


def test_projection_serializes_multiple_related_devices_in_one_query(command, computer, django_assert_num_queries):
    from core.users.models import User

    interface = EquipmentInterface.objects.create(name="USB")
    devices = []
    for index in range(3):
        equipment = Equipment.objects.create(
            sku=f"BUDGET-{index}", name=f"Device {index}", serial_number=f"SERIAL-{index}", kind=computer.kind
        )
        equipment.interfaces.add(interface)
        devices.append(DeviceObservation(f"port-{index}", "USB", "connected", f"Device {index}", f"SERIAL-{index}"))
    observe_devices(replace(command, devices=tuple(devices)))
    with django_assert_num_queries(1):
        data = DeviceConnectionSerializer(list_device_connections(computer_id=computer.pk), many=True).data
    assert len(data) == 3 and all(row["equipment"] and row["interface"] for row in data)
    client = APIClient()
    client.force_authenticate(
        User.objects.create_user(username="query-budget-admin", is_superuser=True, is_staff=True)
    )
    with django_assert_num_queries(2):
        response = client.get("/api/labs/device-connections", {"computer_id": computer.pk})
    assert response.status_code == 200, response.data
    assert response.data["meta"]["pagination"]["count"] == 3


def test_read_api_enforces_existing_labs_access_and_validates_computer_filter(command):
    from core.users.models import User
    from tests.factories import grant_labs_role

    observe_devices(command)
    user = User.objects.create_user(username="device-reader")
    client = APIClient()
    client.force_authenticate(user)
    response = client.get("/api/labs/device-connections", {"computer_id": command.computer_id})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"
    grant_labs_role(user, "coord")
    response = client.get("/api/labs/device-connections", {"computer_id": command.computer_id})
    assert response.status_code == 200, response.data
    assert response.data["meta"]["pagination"]["count"] == 1
    assert response.data["data"][0]["state"]["value"] == "connected"
    assert response.data["data"][0]["interface"] is None
    assert response.data["data"][0]["interface_name"] == "USB"
    for params, code in (
        ({}, "validation_failed"),
        ({"computer_id": "no"}, "validation_failed"),
        ({"computer_id": command.computer_id, "unknown": "value"}, "invalid_query"),
    ):
        response = client.get("/api/labs/device-connections", params)
        assert response.status_code == 400, response.data
        assert response.json()["error"]["code"] == code


def _race(commands):
    barrier = Barrier(len(commands))

    def run(command):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return observe_devices(command)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=len(commands)) as workers:
        return list(workers.map(run, commands))


@pytest.mark.django_db(transaction=True)
def test_concurrent_identical_first_batches_return_in_progress_then_replay(command, monkeypatch):
    entered, release = Event(), Event()
    original = MonitoringEvent.objects.create

    def pause(**kwargs):
        entered.set()
        assert release.wait(timeout=15)
        return original(**kwargs)

    def first():
        close_old_connections()
        try:
            return observe_devices(command)
        finally:
            close_old_connections()

    monkeypatch.setattr(MonitoringEvent.objects, "create", pause)
    with ThreadPoolExecutor(max_workers=1) as workers:
        pending = workers.submit(first)
        try:
            assert entered.wait(timeout=15)
            with pytest.raises(ObservationInProgress) as error:
                observe_devices(command)
            assert error.value.code == "request_in_progress"
        finally:
            release.set()
        result = pending.result(timeout=15)
    replay = observe_devices(command)
    assert not result.is_replayed and replay.is_replayed
    assert DeviceObservationBatch.objects.count() == MonitoringEvent.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_sequences_converge_on_newest_state(command):
    observe_devices(command)
    older = next_report(command, devices=(replace(command.devices[0], name="Older"),))
    newer = replace(older, sequence=3, batch_key=uuid4(), devices=(replace(command.devices[0], name="Newest"),))
    results = _race([older, newer])
    assert all(result.disposition in {"applied", "stale"} for result in results)
    connection = DeviceConnection.objects.get()
    assert connection.sequence == 3 and connection.name == "Newest"
    assert DeviceObservationCursor.objects.get().sequence == 3
    assert DeviceObservationBatch.objects.count() == 3


@pytest.mark.parametrize("capabilities,scope", [(frozenset(), True), (frozenset({"monitoring:report"}), False)])
def test_reporting_requires_explicit_capability_and_computer_scope(command, capabilities, scope):
    from core.common.domain.errors import Forbidden

    actor = ActorContext(
        command.agent_key, "agent", capabilities, frozenset({command.computer_id}) if scope else frozenset()
    )
    with pytest.raises(Forbidden):
        execute_observations(command, actor=actor)
    assert not DeviceObservationBatch.objects.exists()


def test_invalidation_requires_scoped_capability(command):
    from core.common.domain.errors import Forbidden

    observe_devices(command)
    actor = ActorContext("other", "system", frozenset({"monitoring:invalidate"}), frozenset())
    with pytest.raises(Forbidden):
        invalidate_device_connections(InvalidateDeviceConnectionsInput(command.computer_id), actor=actor)
    assert DeviceObservationCursor.objects.get().is_current
