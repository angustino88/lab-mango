"""Rack-mounted equipment: unit positions, overlap guard, rack height, and the capacity the dashboard reads."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.equipment.public import (
    PlaceEquipmentInput,
    highest_rack_unit,
    place_equipment,
    rack_mounted_rows,
    station_installed_totals,
)
from core.labs.features.locations.public import update_station
from core.labs.models import Station
from core.labs.models.resource.equipment.assignment import EquipmentAssignment
from tests.factories import BenchFactory, ComputingEquipmentFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def actor():
    return UserFactory.create(is_superuser=True)


@pytest.fixture
def rack():
    return Station.objects.create(sku="RACK-1", name="Rack 1", rack_units=42)


def _mount(actor, station, unit, height, face="front", **extra):
    equipment = ComputingEquipmentFactory.create(**extra)
    return place_equipment(
        PlaceEquipmentInput(
            equipment_id=equipment.pk,
            station_id=station.pk,
            rack_unit=unit,
            rack_unit_height=height,
            rack_face=face,
        ),
        actor=actor,
    )


def test_units_mount_without_overlap(actor, rack):
    first = _mount(actor, rack, 1, 2)
    _mount(actor, rack, 3, 1)
    assert (first.rack_unit, first.rack_unit_height, first.rack_face) == (1, 2, "front")
    with pytest.raises(ValidationError) as overlap:
        _mount(actor, rack, 2, 2)
    assert "rack_unit" in overlap.value.message_dict
    assert highest_rack_unit(station_id=rack.pk) == 3
    assert [row["rack_unit"] for row in rack_mounted_rows(station_ids=[rack.pk])] == [1, 3]


def test_units_must_fit_the_rack_and_need_a_station(actor, rack):
    with pytest.raises(ValidationError) as too_high:
        _mount(actor, rack, 42, 2)
    assert "42 U" in str(too_high.value)
    shelf = Station.objects.create(sku="SHELF-1", name="Shelf")
    with pytest.raises(ValidationError):
        _mount(actor, shelf, 1, 1)
    equipment = ComputingEquipmentFactory.create()
    with pytest.raises(ValidationError):
        place_equipment(PlaceEquipmentInput(equipment_id=equipment.pk, room_id=None, rack_unit=1), actor=actor)


def test_database_refuses_overlap_and_rack_fields_off_station(actor, rack):
    _mount(actor, rack, 10, 4)
    other = ComputingEquipmentFactory.create()
    with pytest.raises(IntegrityError), transaction.atomic():
        EquipmentAssignment.all_placements.create(
            equipment=other,
            station=rack,
            rack_unit=12,
            rack_unit_height=1,
            rack_face="rear",
            assigned_at=timezone.now(),
        )
    bench = BenchFactory.create()
    with pytest.raises(IntegrityError), transaction.atomic():
        EquipmentAssignment.all_placements.create(
            equipment=other,
            bench=bench,
            rack_unit=1,
            rack_unit_height=1,
            rack_face="front",
            assigned_at=timezone.now(),
        )


def test_rack_cannot_shrink_below_mounted_equipment(actor, rack):
    _mount(actor, rack, 20, 2)
    with pytest.raises(ValidationError) as error:
        update_station(station_id=rack.pk, actor=actor, rack_units=12)
    assert "unit 21" in str(error.value)
    update_station(station_id=rack.pk, actor=actor, rack_units=24)
    rack.refresh_from_db()
    assert rack.rack_units == 24


def test_installed_totals_cover_rack_and_bench_equipment(actor, rack):
    _mount(actor, rack, 1, 1, power_draw_w=300, weight_kg=12)
    bench = BenchFactory.create(setup_location=rack)
    from core.labs.features.equipment.public import AssignEquipmentInput, assign_equipment

    on_bench = ComputingEquipmentFactory.create(power_draw_w=120)
    assign_equipment(AssignEquipmentInput(equipment_id=on_bench.pk, bench_id=bench.pk), actor=actor)
    totals = station_installed_totals(station_ids=[rack.pk])[rack.pk]
    assert totals == {"power_w": 420.0, "weight_kg": 12.0, "units": 2}
