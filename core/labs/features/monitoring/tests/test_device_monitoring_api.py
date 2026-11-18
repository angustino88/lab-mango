"""Lab-wide device monitoring: listing, summary, history, inventory linking, expectations, alerts."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from core.common.contracts import ActorContext
from core.labs.features.monitoring.application.observe_devices import observe_devices as execute_observations
from core.labs.features.monitoring.contracts import DeviceObservation, DeviceObservationInput
from core.labs.models import Equipment, EquipmentAssignment
from core.labs.models.monitoring import DeviceConnection, ExpectedDevice
from core.labs.models.resource.equipment import EquipmentInterface
from core.users.models import User
from core.websocket.models import Notification
from tests.factories import (
    BenchFactory,
    ComputingEquipmentFactory,
    EquipmentCategoryFactory,
    EquipmentKindFactory,
    grant_labs_role,
)

pytestmark = pytest.mark.django_db

DEVICES = "/api/labs/device-connections"
EXPECTED = "/api/labs/expected-devices"


def report(command):
    actor = ActorContext(
        command.agent_key, "system", frozenset({"monitoring:report"}), frozenset({command.computing_id})
    )
    return execute_observations(command, actor=actor)


def snapshot(computing, *devices, sequence=1, generation=None, complete=True, at=None):
    return DeviceObservationInput(
        computing_id=computing.pk,
        agent_key=str(uuid4()),
        generation_key=generation or uuid4(),
        batch_key=uuid4(),
        collector_key="usb",
        sequence=sequence,
        collected_at=at or timezone.now(),
        is_complete=complete,
        devices=tuple(devices),
    )


def device(key, serial="", state="connected", name="Device"):
    return DeviceObservation(key, "USB", state, name, serial)


@pytest.fixture
def staff():
    user = User.objects.create_user(username="monitoring-coordinator")
    grant_labs_role(user, "coord")
    client = APIClient()
    client.force_authenticate(user)
    client.user = user
    return client


@pytest.fixture
def usb():
    return EquipmentInterface.objects.create(name="USB")


@pytest.fixture
def instrument_kind():
    return EquipmentKindFactory(name="Oscilloscope", category=EquipmentCategoryFactory(name="Instrument"))


@pytest.fixture
def scope(usb, instrument_kind):
    computing = ComputingEquipmentFactory(name="Lab PC 07")
    peripheral = Equipment.objects.create(sku="SCOPE-1", name="Scope", serial_number="SER-1", kind=instrument_kind)
    peripheral.interfaces.add(usb)
    return computing, peripheral


def place(equipment, bench):
    EquipmentAssignment.objects.create(equipment=equipment, bench=bench, assigned_at=timezone.now())


def test_lab_wide_list_filters_by_bench_state_attention_and_search(staff, scope):
    computing, _ = scope
    other = ComputingEquipmentFactory(name="Lab PC 03")
    bench = BenchFactory()
    place(computing, bench)
    report(snapshot(computing, device("a", "SER-1"), device("b", "UNKNOWN-9", name="Mystery")))
    report(snapshot(other, device("c", state="disconnected")))

    everything = staff.get(DEVICES).data
    assert everything["meta"]["pagination"]["count"] == 3
    on_bench = staff.get(DEVICES, {"bench_id": bench.pk}).data["data"]
    assert {row["observation_key"] for row in on_bench} == {"a", "b"}
    assert on_bench[0]["bench"] == {"id": bench.pk, "name": bench.name}
    assert [row["observation_key"] for row in staff.get(DEVICES, {"state": "disconnected"}).data["data"]] == ["c"]
    attention = staff.get(DEVICES, {"is_attention_required": "true", "bench_id": bench.pk}).data["data"]
    assert [row["observation_key"] for row in attention] == ["b"] and attention[0]["is_attention_required"] is True
    calm = staff.get(DEVICES, {"is_attention_required": "false", "bench_id": bench.pk}).data["data"]
    assert [row["observation_key"] for row in calm] == ["a"]
    assert [row["observation_key"] for row in staff.get(DEVICES, {"q": "myst"}).data["data"]] == ["b"]


def test_summary_counts_connected_matching_unconfirmed_and_missing(staff, scope, usb, instrument_kind):
    computing, peripheral = scope
    absent = Equipment.objects.create(sku="CAM-1", name="Camera", serial_number="CAM", kind=instrument_kind)
    ExpectedDevice.objects.create(computing=computing, equipment=absent)
    ExpectedDevice.objects.create(computing=computing, equipment=peripheral)
    report(snapshot(computing, device("a", "SER-1"), device("b", "UNKNOWN")))

    summary = staff.get(f"{DEVICES}/summary").data["data"]
    assert summary == {"connected": 2, "needs_matching": 1, "unconfirmed": 0, "missing": 1, "computing_units": 1}
    with freeze_time(timezone.now() + timedelta(minutes=5)):
        later = staff.get(f"{DEVICES}/summary").data["data"]
    assert later["connected"] == 0 and later["unconfirmed"] == 2 and later["missing"] == 0


def test_detail_returns_history_of_state_changes(staff, scope):
    computing, _ = scope
    generation = uuid4()
    start = timezone.now() - timedelta(minutes=10)
    with freeze_time(start):
        report(snapshot(computing, device("a", "SER-1"), generation=generation, at=start))
    with freeze_time(start + timedelta(minutes=1)):
        report(snapshot(computing, generation=generation, sequence=2, at=start + timedelta(minutes=1)))
    with freeze_time(start + timedelta(minutes=2)):
        report(snapshot(computing, generation=generation, sequence=3, at=start + timedelta(minutes=2)))
    with freeze_time(start + timedelta(minutes=3)):
        report(
            snapshot(
                computing,
                device("a", "SER-1"),
                generation=generation,
                sequence=4,
                complete=False,
                at=start + timedelta(minutes=3),
            )
        )
    connection = DeviceConnection.objects.get()

    body = staff.get(f"{DEVICES}/{connection.pk}").data["data"]

    assert [(change["state"]["value"], change["sequence"]) for change in body["history"]] == [
        ("connected", 4),
        ("disconnected", 2),
        ("connected", 1),
    ]
    assert body["first_seen_at"] and body["equipment"]["name"] == "Scope"
    assert staff.get(f"{DEVICES}/999999").status_code == 404


def test_link_records_serial_on_equipment_and_rematches_every_observation(staff, scope, usb, instrument_kind):
    computing, _ = scope
    other = ComputingEquipmentFactory()
    adapter = Equipment.objects.create(sku="UART-1", name="USB-UART adapter", kind=instrument_kind)
    adapter.interfaces.add(usb)
    report(snapshot(computing, device("a", "FT-1")))
    report(snapshot(other, device("z", "FT-1")))
    connection = DeviceConnection.objects.get(computing=computing)
    assert connection.match_status == "unmatched"

    response = staff.post(f"{DEVICES}/{connection.pk}/actions/link", {"equipment_id": adapter.pk}, format="json")

    assert response.status_code == 200, response.data
    assert response.data["data"]["match_status"]["value"] == "matched"
    assert response.data["data"]["equipment"]["id"] == adapter.pk
    adapter.refresh_from_db()
    assert adapter.serial_number == "FT-1" and adapter.last_modified_by == staff.user
    assert DeviceConnection.objects.get(computing=other).equipment_id == adapter.pk
    again = staff.post(f"{DEVICES}/{connection.pk}/actions/link", {"equipment_id": adapter.pk}, format="json")
    assert again.status_code == 200


@pytest.mark.parametrize(
    "case,code",
    [
        ("different_serial", "equipment_serial_conflict"),
        ("serial_in_use", "equipment_serial_in_use"),
        ("no_serial", "serial_unavailable"),
    ],
)
def test_link_never_overwrites_inventory(staff, scope, case, code, instrument_kind):
    computing, peripheral = scope
    target = Equipment.objects.create(
        sku="T-1", name="Target", serial_number="OTHER" if case == "different_serial" else "", kind=instrument_kind
    )
    serial = {"serial_in_use": "SER-1", "no_serial": ""}.get(case, "NEW-1")
    report(snapshot(computing, device("a", serial)))
    connection = DeviceConnection.objects.get()

    response = staff.post(f"{DEVICES}/{connection.pk}/actions/link", {"equipment_id": target.pk}, format="json")

    assert response.status_code == 409, response.data
    assert response.json()["error"]["code"] == code
    target.refresh_from_db()
    assert target.serial_number == ("OTHER" if case == "different_serial" else "")


def test_expected_devices_report_presence_and_can_be_managed(staff, scope):
    computing, peripheral = scope
    created = staff.post(
        EXPECTED,
        {"computing_id": computing.pk, "equipment_id": peripheral.pk, "is_disconnect_alert_enabled": True},
        format="json",
    )
    assert created.status_code == 201, created.data
    expected_id = created.data["data"]["id"]
    assert created.data["data"]["presence"]["value"] == "unconfirmed"
    duplicate = staff.post(EXPECTED, {"computing_id": computing.pk, "equipment_id": peripheral.pk}, format="json")
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "expected_device_exists"
    assert (
        staff.post(EXPECTED, {"computing_id": computing.pk, "equipment_id": computing.pk}, format="json").status_code
        == 422
    )

    report(snapshot(computing))
    assert staff.get(EXPECTED, {"computing_id": computing.pk}).data["data"][0]["presence"]["value"] == "missing"
    report(snapshot(computing, device("a", "SER-1"), sequence=2))
    listed = staff.get(EXPECTED, {"computing_id": computing.pk, "presence": "present"}).data
    assert listed["meta"]["pagination"]["count"] == 1 and listed["data"][0]["last_seen_at"]

    patched = staff.patch(f"{EXPECTED}/{expected_id}", {"is_disconnect_alert_enabled": False}, format="json")
    assert patched.status_code == 200 and patched.data["data"]["is_disconnect_alert_enabled"] is False
    assert staff.delete(f"{EXPECTED}/{expected_id}").status_code == 204
    assert staff.delete(f"{EXPECTED}/{expected_id}").status_code == 404


def test_disconnect_of_expected_device_alerts_its_creator_once(
    staff, scope, monkeypatch, django_capture_on_commit_callbacks
):
    computing, peripheral = scope
    pushed = []
    monkeypatch.setattr(
        "core.labs.features.monitoring.application.alerts.publish_user_notification",
        lambda user_id, message, **kwargs: pushed.append((user_id, message)),
    )
    expected = ExpectedDevice(computing=computing, equipment=peripheral, notify_on_disconnect=True)
    expected.save(actor=staff.user)
    generation = uuid4()
    report(snapshot(computing, device("a", "SER-1"), generation=generation))

    with django_capture_on_commit_callbacks(execute=True):
        report(snapshot(computing, generation=generation, sequence=2))
    with django_capture_on_commit_callbacks(execute=True):
        report(snapshot(computing, generation=generation, sequence=3))

    notification = Notification.objects.get()
    assert notification.target_user_id == staff.user.pk
    assert notification.message == "Scope disconnected from Lab PC 07"
    assert pushed == [(staff.user.pk, "Scope disconnected from Lab PC 07")]


def test_disconnect_without_opt_in_does_not_alert(scope):
    computing, peripheral = scope
    ExpectedDevice.objects.create(computing=computing, equipment=peripheral, notify_on_disconnect=False)
    generation = uuid4()
    report(snapshot(computing, device("a", "SER-1"), generation=generation))
    report(
        snapshot(
            computing, replace(device("a"), state="disconnected"), generation=generation, sequence=2, complete=False
        )
    )
    assert DeviceConnection.objects.get().state == "disconnected"
    assert not Notification.objects.exists()


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", f"{DEVICES}/summary"),
        ("get", f"{DEVICES}/1"),
        ("post", f"{DEVICES}/1/actions/link"),
        ("get", EXPECTED),
        ("post", EXPECTED),
        ("patch", f"{EXPECTED}/1"),
        ("delete", f"{EXPECTED}/1"),
    ],
)
def test_new_endpoints_follow_the_labs_staff_policy(method, path):
    client = APIClient()
    client.force_authenticate(User.objects.create_user(username="plain-user"))
    response = getattr(client, method)(path, {}, format="json") if method != "get" else client.get(path)
    assert response.status_code == 403


def test_event_list_accepts_its_filters_including_computing(staff, scope):
    computing, _ = scope
    other = ComputingEquipmentFactory(name="Lab PC 03")
    bench = BenchFactory()
    place(computing, bench)
    report(snapshot(computing, device("a", "SER-1")))
    report(snapshot(other, device("b")))

    def ids(params):
        response = staff.get("/api/labs/monitoring-events", params)
        assert response.status_code == 200, response.data
        return {row["computer"]["id"] for row in response.data["data"]}

    assert ids({}) == {computing.pk, other.pk}
    assert ids({"computing_id": computing.pk}) == {computing.pk}
    assert ids({"computer_id": other.pk}) == {other.pk}
    assert ids({"lab": bench.pk}) == {computing.pk}
    assert ids({"from_date_time": (timezone.now() - timedelta(hours=1)).isoformat(), "page": 1, "page_size": 10}) == {
        computing.pk,
        other.pk,
    }
    assert staff.get("/api/labs/monitoring-events", {"unknown": "x"}).status_code == 400
