"""Private placement primitives shared by equipment commands (redesign step 1).

Callers hold the ``Equipment`` row lock. Lock order: ``Equipment``, then the target
(``Bench``, ``Station`` or ``Room``), then placement rows.

A unit's room is the room of its active room placement; ``Equipment.storage_room`` was removed
(labs 0018).
"""

from django.core.exceptions import ValidationError
from django.utils import timezone

from core.labs.features.equipment.exceptions import EquipmentAlreadyPlaced, InvalidEquipmentStatus
from core.labs.models import Equipment, Room, Station
from core.labs.models.resource.equipment.assignment import LOCATION_NOTE_MAX_LENGTH, EquipmentAssignment
from core.labs.models.resource.equipment.equipment import GONE_LIFECYCLE_STATES


def lock_active_placement(equipment: Equipment) -> EquipmentAssignment | None:
    """The unit's active placement of any kind, row-locked."""
    return (
        EquipmentAssignment.all_placements.select_for_update()
        .filter(equipment=equipment, unassigned_at__isnull=True)
        .first()
    )


def clean_location_note(value: str | None) -> str:
    note = (value or "").strip()
    if len(note) > LOCATION_NOTE_MAX_LENGTH:
        raise ValidationError({"location_note": f"Use at most {LOCATION_NOTE_MAX_LENGTH} characters."})
    return note


def lock_station(station_id: int) -> Station:
    station = Station.objects.select_for_update(of=("self",)).filter(pk=station_id).first()
    if station is None:
        raise ValidationError({"station_id": "Select a valid station."})
    return station


def lock_room(room_id: int) -> Room:
    room = Room.objects.select_for_update(of=("self",)).filter(pk=room_id).first()
    if room is None:
        raise ValidationError({"room_id": "Select a valid room."})
    return room


def close_placement(placement: EquipmentAssignment, *, actor) -> None:
    placement.unassigned_at = timezone.now()
    placement.last_modified_by = actor
    placement.save(update_fields=("unassigned_at", "last_modified_by", "modified"))


def close_resting_placement(equipment: Equipment, *, actor) -> None:
    """Close an active station, room or untracked placement so the unit can move to a bench."""
    current = lock_active_placement(equipment)
    if current is not None and current.bench_id is None:
        close_placement(current, actor=actor)


def rest_equipment(
    equipment: Equipment,
    *,
    station: Station | None = None,
    room: Room | None = None,
    location_note: str = "",
    actor,
) -> EquipmentAssignment:
    """Place a unit somewhere other than a bench. Idempotent for the same target and note.

    A unit resting elsewhere moves; a unit on a bench must be removed from it first.
    """
    if station is not None and room is not None:
        raise ValidationError({"non_field_errors": "Choose one target: bench, station, room, or a location note."})
    if station is None and room is None and not location_note:
        raise ValidationError({"location_note": "Describe where the equipment is when no target is chosen."})
    if equipment.lifecycle_state in GONE_LIFECYCLE_STATES:
        raise InvalidEquipmentStatus("Equipment that is transferred out, retired or lost cannot be placed.")
    current = lock_active_placement(equipment)
    if current is not None:
        if current.bench_id is not None:
            raise EquipmentAlreadyPlaced()
        same_target = current.station_id == getattr(station, "pk", None) and current.room_id == getattr(
            room, "pk", None
        )
        if same_target:
            if current.location_note != location_note:
                current.location_note = location_note
                current.last_modified_by = actor
                current.save(update_fields=("location_note", "last_modified_by", "modified"))
            return current
        close_placement(current, actor=actor)
    return EquipmentAssignment.all_placements.create(
        equipment=equipment,
        station=station,
        room=room,
        location_note=location_note,
        assigned_at=timezone.now(),
        creator=actor,
        last_modified_by=actor,
    )

