"""Place equipment on a bench, at a station, in a room, or at an untracked place; or remove it."""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from core.labs.models import Bench, Equipment

from ._placement import (
    clean_location_note,
    close_placement,
    lock_active_placement,
    lock_room,
    lock_station,
    rest_equipment,
)
from .assign_equipment import AssignEquipmentInput, assign_equipment
from .unassign_equipment import UnassignEquipmentInput, unassign_equipment


@dataclass(frozen=True, slots=True)
class PlaceEquipmentInput:
    equipment_id: int
    bench_id: int | None = None
    station_id: int | None = None
    room_id: int | None = None
    location_note: str = ""
    role: str = "default"
    position: int = 0


@dataclass(frozen=True, slots=True)
class RemovePlacementInput:
    equipment_id: int


@transaction.atomic
def place_equipment(command: PlaceEquipmentInput, *, actor):
    """Set where a unit is.

    Race guard: the ``Equipment`` row lock, then the target row lock, backed by
    ``one_active_bench_per_equipment`` (one active placement per unit). The current placement,
    a bench included, is closed in the same transaction, so any move is one call. Idempotent: the
    same target returns the active placement.
    """
    targets = [name for name in ("bench_id", "station_id", "room_id") if getattr(command, name) is not None]
    if len(targets) > 1:
        raise ValidationError({"non_field_errors": "Choose one target: bench, station, room, or a location note."})
    note = clean_location_note(command.location_note)
    if command.bench_id is None and (command.role != "default" or command.position != 0):
        raise ValidationError({"role": "Role and position apply to bench placements only."})
    if command.bench_id is not None:
        equipment = Equipment.objects.select_for_update().get(pk=command.equipment_id, deleted_at__isnull=True)
        Bench.objects.select_for_update().get(pk=command.bench_id, deleted_at__isnull=True)
        current = lock_active_placement(equipment)
        if current is not None and current.bench_id is not None and current.bench_id != command.bench_id:
            close_placement(current, actor=actor)  # bench to bench in one call
        placement = assign_equipment(
            AssignEquipmentInput(
                equipment_id=command.equipment_id,
                bench_id=command.bench_id,
                role=command.role,
                position=command.position,
            ),
            actor=actor,
        )
        if placement.location_note != note:
            placement.location_note = note
            placement.last_modified_by = actor
            placement.save(update_fields=("location_note", "last_modified_by", "modified"))
        return placement
    equipment = Equipment.objects.select_for_update().get(pk=command.equipment_id, deleted_at__isnull=True)
    station = lock_station(command.station_id) if command.station_id is not None else None
    room = lock_room(command.room_id) if command.room_id is not None else None
    return rest_equipment(equipment, station=station, room=room, location_note=note, actor=actor)


@transaction.atomic
def remove_placement(command: RemovePlacementInput, *, actor):
    """Close the unit's active placement; afterwards its location is unknown.

    A bench placement is removed through ``unassign_equipment`` (it records the status change).
    Idempotent: no active placement returns ``None``.
    """
    equipment = Equipment.objects.select_for_update().get(pk=command.equipment_id, deleted_at__isnull=True)
    current = lock_active_placement(equipment)
    if current is None:
        return None
    if current.bench_id is not None:
        return unassign_equipment(UnassignEquipmentInput(command.equipment_id), actor=actor)
    close_placement(current, actor=actor)
    return current


def close_placements_for_location(
    *,
    room_id: int | None = None,
    station_id: int | None = None,
    bench_id: int | None = None,
    actor,
) -> int:
    """Close every active equipment placement pointing at a single room, station, or bench.

    Race guard: callers hold the parent ``Room``, ``Station``, or ``Bench`` row lock inside
    their transaction. This helper locks only ``EquipmentAssignment`` rows in ascending ``pk``
    order (never locking ``Equipment``) to avoid lock-order inversion with ``place_equipment`` /
    ``assign_equipment`` (which lock ``Equipment`` then the target location). Returns the count
    of active placements closed for non-deleted equipment.
    """
    targets = [
        (field, value)
        for field, value in (("room_id", room_id), ("station_id", station_id), ("bench_id", bench_id))
        if value is not None
    ]
    if len(targets) != 1:
        raise ValueError("Pass exactly one of room_id, station_id, or bench_id.")
    field, target_id = targets[0]
    from core.labs.models.resource.equipment.assignment import EquipmentAssignment

    placements = list(
        EquipmentAssignment.all_placements.select_for_update()
        .filter(unassigned_at__isnull=True, **{field: target_id})
        .order_by("pk")
    )
    if not placements:
        return 0
    acting_user = actor if getattr(actor, "is_authenticated", False) else None
    live_equipment_ids = set(
        Equipment.objects.filter(
            pk__in=[item.equipment_id for item in placements],
            deleted_at__isnull=True,
        ).values_list("pk", flat=True)
    )
    closed_live = 0
    for placement in placements:
        close_placement(placement, actor=acting_user)
        if placement.equipment_id in live_equipment_ids:
            closed_live += 1
    return closed_live


__all__ = (
    "PlaceEquipmentInput",
    "RemovePlacementInput",
    "close_placements_for_location",
    "place_equipment",
    "remove_placement",
)
