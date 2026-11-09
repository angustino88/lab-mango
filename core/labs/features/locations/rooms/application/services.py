"""Room writes lock the room row before mutating layout, slots, status, or observations."""

from django.core.exceptions import ValidationError

from core.common.db.transactions import apply_fields, atomic_command
from core.labs.features.locations.rooms.application.policies import RoomConflict, grid_positions
from core.labs.models.resource.location.room import Room, RoomStatusRecord
from core.labs.models.resource.location.room_observation import RoomObservation
from core.labs.models.resource.location.room_slot import RoomSlot
from core.labs.models.resource.location.station import Station

ROOM_WRITE_FIELDS = (
    "sku", "name", "label", "department_id", "group_id", "owner_id", "remark", "map_url", "length_m", "width_m",
    "country_id", "city_id", "building_id", "floor", "layout_rows", "layout_columns",
    "usable_height_m", "floor_plan_revision", "floor_plan_url",
    "max_occupancy", "power_capacity_w", "cooling_capacity_w", "network_port_capacity", "utilities",
)
OBSERVATION_WRITE_FIELDS = ("observed_at", "source", "temperature_c", "humidity_percent", "power_usage_w")

_room_atomic_command = atomic_command(RoomConflict)
_apply = apply_fields


def _lock_room(room_id):
    return Room.objects.select_for_update().get(pk=room_id)


def _check_layout_fits(room):
    """Reject layout changes that would strand slots already assigned to stations."""
    room.clean()
    slots = RoomSlot.objects.filter(room=room)
    if room.layout_rows is not None and room.layout_columns is not None:
        # Outside the grid means row >= rows OR column >= columns.
        slots = slots.exclude(row_index__lt=room.layout_rows, col_index__lt=room.layout_columns)
    if Station.objects.filter(slot__in=slots).exists():
        raise RoomConflict("Slots outside the room layout are assigned to stations.")


def _sync_grid(room, actor):
    """Make room slots match the explicit layout grid, adding and pruning unreferenced cells."""
    rows, columns = room.layout_rows, room.layout_columns
    if rows is None or columns is None:
        raise ValidationError({"layout_rows": "Room has no layout to generate slots for."})
    existing = {(slot.row_index, slot.col_index): slot for slot in RoomSlot.objects.filter(room=room)}
    grid = list(grid_positions(rows, columns))
    grid_keys = {(row, column) for row, column, _ in grid}
    stale = [slot for key, slot in existing.items() if key not in grid_keys]
    if stale and Station.objects.filter(slot__in=stale).exists():
        raise RoomConflict("Slots outside the room layout are assigned to stations.")
    RoomSlot.objects.filter(pk__in=[slot.pk for slot in stale]).delete()
    for row, column, code in grid:
        if (row, column) not in existing:
            RoomSlot(room=room, row_index=row, col_index=column, slot_code=code).save(actor=actor)


@_room_atomic_command
def create_room(*, actor, **data):
    room = Room()
    _apply(room, data, ROOM_WRITE_FIELDS)
    room.save(actor=actor)
    return room


@_room_atomic_command
def update_room(*, room_id, actor, **data):
    room = _lock_room(room_id)
    _apply(room, data, ROOM_WRITE_FIELDS)
    _check_layout_fits(room)
    room.save(actor=actor)
    return room


@_room_atomic_command
def delete_room(*, room_id, actor):
    room = _lock_room(room_id)
    if Station.objects.filter(room=room).exists():
        raise RoomConflict("Move or detach stations before deleting the room.")
    room.soft_delete(actor=actor)


@_room_atomic_command
def generate_room_slots(*, room_id, actor):
    room = _lock_room(room_id)
    _sync_grid(room, actor)
    return room


@_room_atomic_command
def record_room_status(*, room_id, actor, status, metadata=None):
    room = _lock_room(room_id)
    record = RoomStatusRecord(room=room, status=status, metadata={} if metadata is None else metadata)
    if not isinstance(record.metadata, dict):
        raise ValidationError({"metadata": "Metadata must be an object."})
    record.full_clean()
    record.save(actor=actor)
    return record


@_room_atomic_command
def record_room_observation(*, room_id, **data):
    room = Room.objects.get(pk=room_id)
    observation = RoomObservation(room=room)
    _apply(observation, data, OBSERVATION_WRITE_FIELDS)
    observation.full_clean()
    observation.save()
    return observation


__all__ = [
    "create_room", "delete_room", "generate_room_slots", "record_room_observation",
    "record_room_status", "update_room",
]
