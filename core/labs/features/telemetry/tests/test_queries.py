"""Placement resolution: target → (room, station), batched and never guessed."""

import pytest
from django.utils import timezone

from core.labs.features.telemetry.contracts import Placement
from core.labs.features.telemetry.queries import resolve_placement
from core.labs.models import Room, Station, StationSlot
from core.labs.models.telemetry import TelemetryTarget
from tests.factories import BenchFactory, ComputingEquipmentFactory, LabEquipmentAssignmentFactory

pytestmark = pytest.mark.django_db


def _target(**resource):
    ((field, value),) = resource.items()
    return TelemetryTarget.objects.create(target_type=field, **resource)


@pytest.fixture
def layout():
    room = Room.objects.create(sku="PL-R-1", name="Room 3")
    station = Station.objects.create(sku="PL-S-1", name="Station A", room=room)
    slot = StationSlot.objects.create(station=station, position_index=1, slot_code="A1")
    bench = BenchFactory(setup_location=station, station_slot=slot)
    equipment = ComputingEquipmentFactory()
    LabEquipmentAssignmentFactory(bench=bench, equipment=equipment)
    return room, station, bench, equipment


def test_each_target_type_resolves_to_room_and_station(layout):
    room, station, bench, equipment = layout
    targets = [_target(room=room), _target(station=station), _target(bench=bench), _target(equipment=equipment)]

    placements = resolve_placement(target_ids=[target.pk for target in targets])

    assert placements == {
        targets[0].pk: Placement(room_id=room.pk, station_id=None),
        targets[1].pk: Placement(room_id=room.pk, station_id=station.pk),
        targets[2].pk: Placement(room_id=room.pk, station_id=station.pk),
        targets[3].pk: Placement(room_id=room.pk, station_id=station.pk),
    }


def test_unlocated_targets_are_absent_not_guessed(layout):
    room, _, _, _ = layout
    roomless_station = Station.objects.create(sku="PL-S-2", name="Unplaced station")
    slotless_bench = BenchFactory()
    unassigned_equipment = ComputingEquipmentFactory()
    targets = [
        _target(station=roomless_station),
        _target(bench=slotless_bench),
        _target(equipment=unassigned_equipment),
    ]

    assert resolve_placement(target_ids=[target.pk for target in targets]) == {}


def test_soft_deleted_links_make_a_target_unlocated(layout):
    room, station, bench, equipment = layout
    room_target, equipment_target = _target(room=room), _target(equipment=equipment)
    Room.objects.filter(pk=room.pk).update(deleted_at=timezone.now())

    assert resolve_placement(target_ids=[room_target.pk, equipment_target.pk]) == {}


def test_closed_assignment_unlocates_equipment(layout):
    _, _, _, equipment = layout
    target = _target(equipment=equipment)
    equipment.bench_assignments.update(unassigned_at=timezone.now())

    assert resolve_placement(target_ids=[target.pk]) == {}


def test_query_count_does_not_grow_with_batch_size(layout, django_assert_max_num_queries):
    room, station, bench, equipment = layout
    targets = [_target(room=room), _target(station=station), _target(bench=bench), _target(equipment=equipment)]
    for index in range(10):
        extra_station = Station.objects.create(sku=f"PL-S-X{index}", name=f"S{index}", room=room)
        targets.append(_target(station=extra_station))

    with django_assert_max_num_queries(5):
        placements = resolve_placement(target_ids=[target.pk for target in targets])

    assert len(placements) == len(targets)


def test_empty_input_runs_one_query(django_assert_max_num_queries):
    with django_assert_max_num_queries(1):
        assert resolve_placement(target_ids=[]) == {}
