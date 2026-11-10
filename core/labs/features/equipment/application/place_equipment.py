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


__all__ = ("PlaceEquipmentInput", "RemovePlacementInput", "place_equipment", "remove_placement")
