"""Equipment lifecycle state and condition (redesign step 2)."""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.equipment.application import (
    ChangeConditionInput,
    ChangeLifecycleInput,
    CreateEquipmentInput,
    PlaceEquipmentInput,
    change_condition,
    change_lifecycle,
    create_equipment,
    place_equipment,
)
from core.labs.features.equipment.exceptions import EquipmentAlreadyPlaced, InvalidEquipmentStatus
from core.labs.features.equipment.public import (
    equipment_state_timelines,
    get_equipment_status_summary,
    list_equipment,
)
from core.labs.models import (
    Bench,
    ComputingEquipment,
    Equipment,
    EquipmentBooking,
    EquipmentCategory,
    EquipmentEvent,
    EquipmentKind,
    EquipmentPlacement,
    Room,
)

LIFECYCLES = ("planned", "in_service", "transferred_out", "retired", "lost")
ALLOWED = {
    ("planned", "in_service"),
    ("planned", "retired"),
    ("in_service", "transferred_out"),
    ("in_service", "retired"),
    ("in_service", "lost"),
    ("lost", "in_service"),
    ("lost", "retired"),
    ("transferred_out", "in_service"),
}


@pytest.fixture
def kind(db):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    return EquipmentKind.objects.create(category=category, name="State PC")


@pytest.fixture
def unit(kind):
    return ComputingEquipment.objects.create(sku="ST-1", name="State unit", kind=kind)


def _lifecycle(unit, state, **extra):
    return change_lifecycle(ChangeLifecycleInput(equipment_id=unit.pk, lifecycle_state=state, **extra), actor=None)


def _condition(unit, condition, reason=""):
    return change_condition(ChangeConditionInput(equipment_id=unit.pk, condition=condition, reason=reason), actor=None)


def _display(unit):
    return list_equipment().get(pk=unit.pk).display_status


def _events(unit, axis=None):
    rows = EquipmentEvent.objects.filter(equipment=unit)
    if axis:
        rows = rows.filter(axis=axis)
    return list(rows.values_list("axis", "from_value", "to_value"))


# Creation --------------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_defaults_to_in_service_and_records_initial_event(kind):
    unit = create_equipment(
        CreateEquipmentInput(fields=(("kind", kind.pk), ("sku", "ST-C1"), ("name", "n"))), actor=None
    )
    assert (unit.lifecycle_state, unit.condition) == ("in_service", "operational")
    assert _events(unit) == [("lifecycle", "", "in_service")]


@pytest.mark.django_db
def test_create_planned_and_reject_other_lifecycle(kind):
    planned = create_equipment(
        CreateEquipmentInput(
            fields=(("kind", kind.pk), ("sku", "ST-C2"), ("name", "n"), ("lifecycle_state", "planned"))
        ),
        actor=None,
    )
    assert _display(planned) == "on_order"
    with pytest.raises(ValidationError):
        create_equipment(
            CreateEquipmentInput(
                fields=(("kind", kind.pk), ("sku", "ST-C3"), ("name", "n"), ("lifecycle_state", "lost"))
            ),
            actor=None,
        )


# Condition -------------------------------------------------------------------------------


@pytest.mark.django_db
def test_condition_change_records_event_and_is_idempotent(unit):
    _condition(unit, "in_maintenance", reason="Fan noise")
    _condition(unit, "in_maintenance")
    unit.refresh_from_db()
    assert unit.condition == "in_maintenance"
    assert _events(unit, "condition") == [("condition", "operational", "in_maintenance")]
    assert EquipmentEvent.objects.get(equipment=unit, axis="condition").reason == "Fan noise"


@pytest.mark.django_db
def test_condition_change_never_moves_a_placement(unit):
    bench = Bench.objects.create(sku="ST-B1", name="Bench")
    placement = place_equipment(PlaceEquipmentInput(equipment_id=unit.pk, bench_id=bench.pk), actor=None)
    _condition(unit, "out_of_service")
    placement.refresh_from_db()
    assert placement.unassigned_at is None
    assert _display(unit) == "broken"


@pytest.mark.django_db
def test_condition_changes_only_in_service(unit):
    _lifecycle(unit, "lost")
    with pytest.raises(InvalidEquipmentStatus):
        _condition(unit, "in_maintenance")


@pytest.mark.django_db
def test_condition_only_in_service_is_a_database_constraint(unit):
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        Equipment.objects.filter(pk=unit.pk).update(lifecycle_state="lost", condition="out_of_service")
    assert "equipment_condition_only_in_service" in str(error.value)


# Lifecycle -------------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("source", LIFECYCLES)
@pytest.mark.parametrize("target", LIFECYCLES)
def test_lifecycle_transition_table(kind, source, target):
    unit = ComputingEquipment.objects.create(
        sku=f"ST-T-{source}-{target}", name="t", kind=kind, lifecycle_state=source
    )
    extra = {"receiving_organisation": "Partner lab"} if target == "transferred_out" else {}
    if source == target or (source, target) in ALLOWED:
        _lifecycle(unit, target, **extra)
        unit.refresh_from_db()
        assert unit.lifecycle_state == target
        expected = [] if source == target else [("lifecycle", source, target)]
        assert _events(unit, "lifecycle") == expected
    else:
        with pytest.raises(InvalidEquipmentStatus):
            _lifecycle(unit, target, **extra)


@pytest.mark.django_db
def test_leaving_service_resets_condition_with_its_own_event(unit):
    _condition(unit, "out_of_service")
    _lifecycle(unit, "retired", reason="Scrapped")
    unit.refresh_from_db()
    assert (unit.lifecycle_state, unit.condition) == ("retired", "operational")
    assert _events(unit) == [
        ("condition", "operational", "out_of_service"),
        ("condition", "out_of_service", "operational"),
        ("lifecycle", "in_service", "retired"),
    ]


@pytest.mark.django_db
def test_transfer_requires_and_records_receiving_organisation(unit):
    with pytest.raises(ValidationError):
        _lifecycle(unit, "transferred_out")
    _lifecycle(unit, "transferred_out", receiving_organisation="  Partner lab ", transfer_date=timezone.localdate())
    event = EquipmentEvent.objects.get(equipment=unit, to_value="transferred_out")
    assert event.details["receiving_organisation"] == "Partner lab"
    assert _display(unit) == "transferred"


@pytest.mark.django_db
def test_gone_states_refuse_bench_close_resting_placement_and_cancel_reserved_bookings(unit):
    bench = Bench.objects.create(sku="ST-B2", name="Bench")
    place_equipment(PlaceEquipmentInput(equipment_id=unit.pk, bench_id=bench.pk), actor=None)
    with pytest.raises(EquipmentAlreadyPlaced):
        _lifecycle(unit, "lost")

    EquipmentPlacement.objects.filter(equipment=unit).update(unassigned_at=timezone.now())
    room = Room.objects.create(sku="ST-R1", name="Store")
    place_equipment(PlaceEquipmentInput(equipment_id=unit.pk, room_id=room.pk), actor=None)
    start = timezone.now() + timedelta(days=1)
    booking = EquipmentBooking.objects.create(
        equipment=unit, booking_code="ST-BK-1", starts_at=start, ends_at=start + timedelta(hours=1)
    )

    _lifecycle(unit, "lost", reason="Not found at inventory")

    booking.refresh_from_db()
    assert booking.status == "cancelled" and booking.cancellation_reason == "Not found at inventory"
    assert not EquipmentPlacement.objects.filter(equipment=unit, unassigned_at__isnull=True).exists()
    lost = EquipmentEvent.objects.get(equipment=unit, to_value="lost")
    assert lost.details["cancelled_booking_ids"] == [booking.pk]


@pytest.mark.django_db
def test_placement_gating_by_lifecycle(kind):
    planned = ComputingEquipment.objects.create(sku="ST-P1", name="p", kind=kind, lifecycle_state="planned")
    bench = Bench.objects.create(sku="ST-B3", name="Bench")
    room = Room.objects.create(sku="ST-R2", name="Store")
    with pytest.raises(InvalidEquipmentStatus):
        place_equipment(PlaceEquipmentInput(equipment_id=planned.pk, bench_id=bench.pk), actor=None)
    place_equipment(PlaceEquipmentInput(equipment_id=planned.pk, room_id=room.pk), actor=None)  # awaiting service
    lost = ComputingEquipment.objects.create(sku="ST-P2", name="l", kind=kind, lifecycle_state="lost")
    with pytest.raises(InvalidEquipmentStatus):
        place_equipment(PlaceEquipmentInput(equipment_id=lost.pk, location_note="Found in a drawer?"), actor=None)


# Display status ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_display_status_priority(unit, kind):
    bench = Bench.objects.create(sku="ST-B4", name="Bench")
    assert _display(unit) == "available"
    unit.calibration_required = True
    unit.save(update_fields=["calibration_required"])
    assert _display(unit) == "calibration_overdue"
    place_equipment(PlaceEquipmentInput(equipment_id=unit.pk, bench_id=bench.pk), actor=None)
    assert _display(unit) == "in_use"  # bench outranks calibration
    _condition(unit, "in_maintenance")
    assert _display(unit) == "maintenance"
    _condition(unit, "out_of_service")
    assert _display(unit) == "broken"  # broken outranks maintenance and the bench
    resting = ComputingEquipment.objects.create(sku="ST-D2", name="r", kind=kind)
    place_equipment(PlaceEquipmentInput(equipment_id=resting.pk, location_note="Cabinet 3"), actor=None)
    assert _display(resting) == "available"  # resting somewhere is not "in use"


@pytest.mark.django_db
def test_status_summary_counts_display_status(unit, kind):
    ComputingEquipment.objects.create(sku="ST-S2", name="s", kind=kind, lifecycle_state="planned")
    _condition(unit, "in_maintenance")
    counts = {row["status"]["value"]: row["resource_count"] for row in get_equipment_status_summary()["statuses"]}
    assert counts["maintenance"] == 1 and counts["on_order"] == 1 and counts["available"] == 0


@pytest.mark.django_db
def test_state_timelines_replay_history(unit):
    _condition(unit, "out_of_service")
    _condition(unit, "operational")
    timeline = equipment_state_timelines(until=timezone.now() + timedelta(seconds=1))[unit.pk]["timeline"]
    assert [label for _, label in timeline] == ["available", "broken", "available"]
    assert timeline[0][0] == unit.created
