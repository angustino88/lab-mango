"""API tests for force-deleting rooms, stations, and benches."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.equipment.public import PlaceEquipmentInput, place_equipment
from core.labs.features.equipment.tests.roles import grant_labs_role
from core.labs.models import (
    Bench,
    BenchBooking,
    Equipment,
    EquipmentAssignment,
    EquipmentCategory,
    EquipmentKind,
    ResourceChangeLog,
    ResourceLifecycleStatus,
    Room,
    RoomSlot,
    Station,
    StationSlot,
)
from core.labs.models.booking.base import BookingStatus
from core.labs.models.resource.equipment.equipment import EquipmentLifecycleState

User = get_user_model()
ROOT = "/api/labs/"


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.fixture
def coordinator(db):
    return grant_labs_role(User.objects.create_user(username="fd-space-coord"), "coord")


@pytest.fixture
def member(db):
    return grant_labs_role(User.objects.create_user(username="fd-space-member"), "member")


@pytest.fixture
def equipment_kind(db):
    category = EquipmentCategory.objects.create(key="computing", name="Computing", definition="Computing units")
    return EquipmentKind.objects.create(category=category, name="Workstation")


@pytest.mark.django_db
def test_force_delete_room_detaches_stations_preserves_lifecycle_and_clears_resting_equipment(
    coordinator, equipment_kind
):
    room = Room.objects.create(sku="FD-RM-01", name="Decommissioned Lab")
    slot = RoomSlot.objects.create(room=room, row_index=0, col_index=0, slot_code="A1")
    station = Station.objects.create(
        sku="FD-ST-01",
        name="Rack Alpha",
        room=room,
        slot=slot,
        lifecycle_status=ResourceLifecycleStatus.IN_SERVICE,
    )
    unit = Equipment.objects.create(kind=equipment_kind, sku="FD-EQ-RM", name="Room Spare")
    place_equipment(PlaceEquipmentInput(equipment_id=unit.pk, room_id=room.pk), actor=coordinator)

    response = _client(coordinator).post(
        ROOT + f"rooms/{room.pk}/actions/force-delete",
        {"reason": "Lab room closed for building renovation", "confirm": True},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["data"] == {"id": room.pk, "released": {"stations": 1, "equipment": 1}}

    room_row = Room.all_objects.get(pk=room.pk)
    assert room_row.deleted_at is not None

    station.refresh_from_db()
    assert station.room_id is None
    assert station.slot_id is None
    assert station.lifecycle_status == ResourceLifecycleStatus.IN_SERVICE

    unit.refresh_from_db()
    assert unit.lifecycle_state == EquipmentLifecycleState.IN_SERVICE
    assert not EquipmentAssignment.all_placements.filter(equipment=unit, unassigned_at__isnull=True).exists()

    ct = ContentType.objects.get_for_model(Room, for_concrete_model=False)
    log = ResourceChangeLog.objects.get(
        resource_content_type=ct, resource_object_id=str(room.pk), field_name="force_delete"
    )
    assert log.action == ResourceChangeLog.Action.DELETE
    assert log.new_value["reason"] == "Lab room closed for building renovation"
    assert log.new_value["released"] == {"stations": 1, "equipment": 1}

    second = _client(coordinator).post(
        ROOT + f"rooms/{room.pk}/actions/force-delete",
        {"reason": "Retry after delete", "confirm": True},
        format="json",
    )
    assert second.status_code == 404


@pytest.mark.django_db
def test_force_delete_station_detaches_benches_preserves_lifecycle_and_clears_resting_equipment(
    coordinator, equipment_kind
):
    room = Room.objects.create(sku="FD-RM-02", name="Main Room")
    room_slot = RoomSlot.objects.create(room=room, row_index=0, col_index=0, slot_code="A1")
    station = Station.objects.create(sku="FD-ST-02", name="Removed Rack", room=room, slot=room_slot)
    station_slot = StationSlot.objects.create(station=station, position_index=1, slot_code="S1")
    bench = Bench.objects.create(
        sku="FD-BN-02",
        name="Bench Beta",
        setup_location=station,
        station_slot=station_slot,
        lifecycle_status=ResourceLifecycleStatus.IN_SERVICE,
    )
    unit = Equipment.objects.create(kind=equipment_kind, sku="FD-EQ-ST", name="Station Spare")
    place_equipment(PlaceEquipmentInput(equipment_id=unit.pk, station_id=station.pk), actor=coordinator)

    response = _client(coordinator).post(
        ROOT + f"stations/{station.pk}/actions/force-delete",
        {"reason": "Rack removed from floor", "confirm": True},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["data"] == {"id": station.pk, "released": {"benches": 1, "equipment": 1}}

    station_row = Station.all_objects.get(pk=station.pk)
    assert station_row.deleted_at is not None
    assert station_row.room_id is None
    assert station_row.slot_id is None

    bench.refresh_from_db()
    assert bench.setup_location_id is None
    assert bench.station_slot_id is None
    assert bench.lifecycle_status == ResourceLifecycleStatus.IN_SERVICE

    unit.refresh_from_db()
    assert unit.lifecycle_state == EquipmentLifecycleState.IN_SERVICE
    assert not EquipmentAssignment.all_placements.filter(equipment=unit, unassigned_at__isnull=True).exists()

    second = _client(coordinator).post(
        ROOT + f"stations/{station.pk}/actions/force-delete",
        {"reason": "Retry after delete", "confirm": True},
        format="json",
    )
    assert second.status_code == 404


@pytest.mark.django_db
def test_force_delete_bench_unassigns_equipment_and_cancels_active_bookings(coordinator, equipment_kind):
    station = Station.objects.create(sku="FD-ST-03", name="Bench Host")
    slot = StationSlot.objects.create(station=station, position_index=1, slot_code="S1")
    bench = Bench.objects.create(sku="FD-BN-03", name="Retired Bench", setup_location=station, station_slot=slot)
    unit = Equipment.objects.create(kind=equipment_kind, sku="FD-EQ-BN", name="Bench PC")
    now = timezone.now()
    EquipmentAssignment.objects.create(equipment=unit, bench=bench, assigned_at=now)
    booking = BenchBooking.objects.create(
        bench=bench,
        booking_code="FD-BB-01",
        starts_at=now + timedelta(hours=1),
        ends_at=now + timedelta(hours=3),
    )

    response = _client(coordinator).post(
        ROOT + f"benches/{bench.pk}/actions/force-delete",
        {"reason": "Bench dismantled for hardware refresh", "confirm": True},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["data"] == {"id": bench.pk, "released": {"equipment": 1, "bookings": 1}}

    bench_row = Bench.all_objects.get(pk=bench.pk)
    assert bench_row.deleted_at is not None
    assert bench_row.setup_location_id is None
    assert bench_row.station_slot_id is None

    unit.refresh_from_db()
    assert unit.lifecycle_state == EquipmentLifecycleState.IN_SERVICE
    assert not EquipmentAssignment.all_placements.filter(equipment=unit, unassigned_at__isnull=True).exists()

    booking.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED
    assert "Bench dismantled for hardware refresh" in booking.cancellation_reason

    second = _client(coordinator).post(
        ROOT + f"benches/{bench.pk}/actions/force-delete",
        {"reason": "Retry after delete", "confirm": True},
        format="json",
    )
    assert second.status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        ("rooms/{id}/actions/force-delete", {"reason": "Valid reason", "confirm": False}),
        ("rooms/{id}/actions/force-delete", {"reason": "no", "confirm": True}),
        ("stations/{id}/actions/force-delete", {"reason": "Valid reason", "confirm": False}),
        ("stations/{id}/actions/force-delete", {"reason": "no", "confirm": True}),
        ("benches/{id}/actions/force-delete", {"reason": "Valid reason", "confirm": False}),
        ("benches/{id}/actions/force-delete", {"reason": "no", "confirm": True}),
    ],
)
def test_force_delete_spaces_rejects_invalid_payloads(coordinator, endpoint, payload):
    room = Room.objects.create(sku="FD-VAL-RM", name="Val Room")
    station = Station.objects.create(sku="FD-VAL-ST", name="Val Station")
    bench = Bench.objects.create(sku="FD-VAL-BN", name="Val Bench")
    target_id = room.pk if endpoint.startswith("rooms") else station.pk if endpoint.startswith("stations") else bench.pk

    response = _client(coordinator).post(ROOT + endpoint.format(id=target_id), payload, format="json")
    assert response.status_code == 422, response.data


@pytest.mark.django_db
def test_force_delete_spaces_enforces_lab_operations_permission(member):
    room = Room.objects.create(sku="FD-PERM-RM", name="Perm Room")
    station = Station.objects.create(sku="FD-PERM-ST", name="Perm Station")
    bench = Bench.objects.create(sku="FD-PERM-BN", name="Perm Bench")
    payload = {"reason": "Unauthorized attempt", "confirm": True}

    for path in (
        f"rooms/{room.pk}/actions/force-delete",
        f"stations/{station.pk}/actions/force-delete",
        f"benches/{bench.pk}/actions/force-delete",
    ):
        assert _client().post(ROOT + path, payload, format="json").status_code == 401
        assert _client(member).post(ROOT + path, payload, format="json").status_code == 403


@pytest.mark.django_db
def test_force_delete_bench_via_django_client_with_jwt_returns_json(coordinator):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    bench = Bench.objects.create(sku="FD-JWT-BN", name="JWT Bench")
    token = str(RefreshToken.for_user(coordinator).access_token)
    client = Client(enforce_csrf_checks=True)
    response = client.post(
        ROOT + f"benches/{bench.pk}/actions/force-delete",
        data={"reason": "Operator cleanup via browser JWT", "confirm": True},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 200, response.content
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["data"] == {"id": bench.pk, "released": {"equipment": 0, "bookings": 0}}

