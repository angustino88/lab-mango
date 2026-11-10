"""Equipment placement (redesign step 1): constraints, commands, readers, location guards."""

import threading
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.utils import timezone

from core.labs.features.equipment.application import (
    DeleteEquipmentInput,
    PlaceEquipmentInput,
    RemovePlacementInput,
    UpdateEquipmentInput,
    delete_equipment,
    place_equipment,
    remove_placement,
    update_equipment,
)
from core.labs.features.equipment.exceptions import EquipmentAlreadyPlaced
from core.labs.features.equipment.public import get_active_placement, inactive_equipment_candidates
from core.labs.features.locations.public import LocationConflict, RoomConflict, delete_room, delete_station
from core.labs.models import (
    Bench,
    ComputingActivity,
    ComputingEquipment,
    Equipment,
    EquipmentAssignment,
    EquipmentCategory,
    EquipmentKind,
    EquipmentPlacement,
    EquipmentStatusRecord,
    Room,
    Station,
)


@pytest.fixture
def kind(db):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    return EquipmentKind.objects.create(category=category, name="Placement PC")


@pytest.fixture
def unit(kind):
    return ComputingEquipment.objects.create(sku="PL-1", name="Placement unit", kind=kind)


@pytest.fixture
def room(db):
    return Room.objects.create(sku="PL-ROOM-1", name="Store A")


@pytest.fixture
def other_room(db):
    return Room.objects.create(sku="PL-ROOM-2", name="Store B")


@pytest.fixture
def station(room):
    return Station.objects.create(sku="PL-ST-1", name="Station 1", room=room)


@pytest.fixture
def bench(db):
    return Bench.objects.create(sku="PL-BENCH-1", name="Bench 1")


def _place(unit, **target):
    return place_equipment(PlaceEquipmentInput(equipment_id=unit.pk, **target), actor=None)


def _active(unit):
    return EquipmentPlacement.objects.filter(equipment=unit, unassigned_at__isnull=True)


# Constraints -------------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "fields",
    [
        {"bench": "bench", "room": "room"},
        {"station": "station", "room": "room"},
        {"location_note": ""},
    ],
)
def test_one_target_constraint(unit, bench, room, station, fields):
    resolved = {
        name: {"bench": bench, "room": room, "station": station}.get(value, value) for name, value in fields.items()
    }
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        EquipmentPlacement.objects.create(equipment=unit, assigned_at=timezone.now(), **resolved)
    assert "equipment_placement_one_target" in str(error.value)


@pytest.mark.django_db
def test_bench_fields_constraint(unit, room):
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        EquipmentPlacement.objects.create(equipment=unit, room=room, role="primary", assigned_at=timezone.now())
    assert "equipment_placement_bench_fields" in str(error.value)


@pytest.mark.django_db
def test_one_active_placement_per_unit_across_kinds(unit, room):
    EquipmentPlacement.objects.create(equipment=unit, room=room, assigned_at=timezone.now())
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        EquipmentPlacement.objects.create(equipment=unit, location_note="Cabinet 3", assigned_at=timezone.now())
    assert "one_active_bench_per_equipment" in str(error.value)


@pytest.mark.django_db
def test_assignment_manager_shows_bench_placements_only(unit, room):
    EquipmentPlacement.objects.create(equipment=unit, room=room, assigned_at=timezone.now())
    assert not EquipmentAssignment.objects.filter(equipment=unit).exists()
    assert not unit.bench_assignments.exists()
    assert EquipmentAssignment.all_placements.filter(equipment=unit).count() == 1


# Commands ----------------------------------------------------------------------------------


@pytest.mark.django_db
def test_place_in_room_mirrors_storage_room_and_is_idempotent(unit, room):
    first = _place(unit, room_id=room.pk, location_note="Shelf B")
    again = _place(unit, room_id=room.pk, location_note="Shelf B")
    unit.refresh_from_db()
    assert first.pk == again.pk
    assert unit.storage_room_id == room.pk
    assert get_active_placement(equipment_id=unit.pk).target_type == "room"
    assert _active(unit).count() == 1


@pytest.mark.django_db
def test_move_between_resting_places_closes_previous(unit, room, station):
    first = _place(unit, room_id=room.pk)
    second = _place(unit, station_id=station.pk)
    third = _place(unit, location_note="Borrowed cabinet, building 2")
    first.refresh_from_db()
    second.refresh_from_db()
    unit.refresh_from_db()
    assert first.unassigned_at is not None and second.unassigned_at is not None
    assert third.target_type == "note"
    assert unit.storage_room_id is None
    assert _active(unit).count() == 1


@pytest.mark.django_db
def test_room_to_bench_moves_and_records_in_use(unit, room, bench):
    resting = _place(unit, room_id=room.pk)
    placement = _place(unit, bench_id=bench.pk)
    resting.refresh_from_db()
    unit.refresh_from_db()
    assert resting.unassigned_at is not None
    assert placement.bench_id == bench.pk
    assert unit.storage_room_id is None
    assert EquipmentStatusRecord.objects.filter(equipment=unit).latest("created").status == "in_use"


@pytest.mark.django_db
def test_bench_to_room_requires_leaving_the_bench(unit, room, bench):
    on_bench = _place(unit, bench_id=bench.pk)
    with pytest.raises(EquipmentAlreadyPlaced):
        _place(unit, room_id=room.pk)
    assert list(_active(unit)) == [on_bench]


@pytest.mark.django_db
def test_invalid_targets(unit, room, station):
    with pytest.raises(ValidationError):
        _place(unit)
    with pytest.raises(ValidationError):
        _place(unit, room_id=room.pk, station_id=station.pk)
    with pytest.raises(ValidationError):
        _place(unit, room_id=room.pk, role="primary")
    with pytest.raises(ValidationError):
        _place(unit, location_note="x" * 256)
    Room.objects.filter(pk=room.pk).update(deleted_at=timezone.now())
    with pytest.raises(ValidationError):
        _place(unit, room_id=room.pk)
    assert not _active(unit).exists()


@pytest.mark.django_db
def test_remove_placement(unit, room, bench):
    _place(unit, room_id=room.pk)
    closed = remove_placement(RemovePlacementInput(unit.pk), actor=None)
    unit.refresh_from_db()
    assert closed.unassigned_at is not None and unit.storage_room_id is None
    assert remove_placement(RemovePlacementInput(unit.pk), actor=None) is None
    _place(unit, bench_id=bench.pk)
    remove_placement(RemovePlacementInput(unit.pk), actor=None)
    assert not _active(unit).exists()
    assert EquipmentStatusRecord.objects.filter(equipment=unit).latest("created").status == "available"


# Deprecated storage_room input ------------------------------------------------------------


def _update(unit, **fields):
    return update_equipment(
        UpdateEquipmentInput(equipment_id=unit.pk, model=ComputingEquipment, fields=tuple(fields.items())),
        actor=None,
    )


@pytest.mark.django_db
def test_storage_room_update_becomes_a_room_placement(unit, room, other_room):
    _update(unit, storage_room=room)
    assert get_active_placement(equipment_id=unit.pk).room_id == room.pk
    _update(unit, storage_room=other_room)
    assert get_active_placement(equipment_id=unit.pk).room_id == other_room.pk
    _update(unit, storage_room=None)
    unit.refresh_from_db()
    assert not _active(unit).exists() and unit.storage_room_id is None


@pytest.mark.django_db
def test_storage_room_on_bench_unit_unchanged_is_noop_changed_is_conflict(unit, room, other_room, bench):
    _place(unit, bench_id=bench.pk)
    Equipment.objects.filter(pk=unit.pk).update(storage_room=room)  # legacy value kept by the backfill
    _update(unit, storage_room=room, name="Renamed")
    unit.refresh_from_db()
    assert unit.name == "Renamed"
    with pytest.raises(EquipmentAlreadyPlaced):
        _update(unit, storage_room=other_room)


@pytest.mark.django_db
def test_delete_closes_resting_placement(unit, room):
    _place(unit, room_id=room.pk)
    delete_equipment(DeleteEquipmentInput(equipment_id=unit.pk, model=ComputingEquipment), actor=None)
    assert not _active(unit).exists()


# Readers and location guards ---------------------------------------------------------------


@pytest.mark.django_db
def test_inactivity_candidates_ignore_non_bench_placements(unit, room, bench):
    now = timezone.now()
    ComputingActivity.objects.update_or_create(
        computing=unit,
        defaults={
            "status": "inactive",
            "last_agent_report_at": now - timedelta(minutes=1),
            "inactive_at": now - timedelta(hours=2),
            "booking_code": "BK-1",
        },
    )
    EquipmentPlacement.objects.create(equipment=unit, room=room, assigned_at=now - timedelta(hours=3))
    assert inactive_equipment_candidates(now=now) == []
    remove_placement(RemovePlacementInput(unit.pk), actor=None)
    EquipmentPlacement.objects.create(equipment=unit, bench=bench, assigned_at=now - timedelta(hours=3))
    assert [row.equipment_id for row in inactive_equipment_candidates(now=now)] == [unit.pk]


@pytest.mark.django_db
def test_room_and_station_cannot_be_deleted_while_equipment_rests_there(unit, kind, room, other_room):
    station = Station.objects.create(sku="PL-ST-2", name="Station 2")
    _place(unit, room_id=other_room.pk)
    with pytest.raises(RoomConflict):
        delete_room(room_id=other_room.pk, actor=None)
    second = ComputingEquipment.objects.create(sku="PL-2", name="Second", kind=kind)
    _place(second, station_id=station.pk)
    with pytest.raises(LocationConflict):
        delete_station(station_id=station.pk, actor=None)
    remove_placement(RemovePlacementInput(unit.pk), actor=None)
    delete_room(room_id=other_room.pk, actor=None)


# Concurrency (PostgreSQL) ------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_placements_leave_one_active(kind):
    unit = ComputingEquipment.objects.create(sku="PL-C-1", name="Concurrent", kind=kind)
    rooms = [Room.objects.create(sku=f"PL-C-R{index}", name=f"Room {index}") for index in range(2)]
    barrier = threading.Barrier(2)
    errors = []

    def place(room_id):
        try:
            barrier.wait()
            place_equipment(PlaceEquipmentInput(equipment_id=unit.pk, room_id=room_id), actor=None)
        except Exception as error:  # noqa: BLE001 - collected and asserted below
            errors.append(error)
        finally:
            close_old_connections()

    threads = [threading.Thread(target=place, args=(room.pk,)) for room in rooms]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    active = list(EquipmentPlacement.objects.filter(equipment=unit, unassigned_at__isnull=True))
    assert len(active) == 1
    unit.refresh_from_db()
    assert unit.storage_room_id == active[0].room_id
