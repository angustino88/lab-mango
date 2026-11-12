"""Station writes lock rooms (sorted), then station, then slots, never bench rows.

Bench commands must lock old/new stations in PK order before locking benches
and validate aggregate allocations. This shared protocol serializes station
capacity reductions with bench placement/edits without nullable lock joins.
"""

from django.core.exceptions import ValidationError

from core.common.db.transactions import apply_fields, atomic_command
from core.labs.features.equipment.public import has_active_placements
from core.labs.features.locations.exceptions import LocationConflict
from core.labs.features.locations.stations.application.policies import (
    validate_occupied_slot,
    validate_room_capacity,
    validate_room_slot,
    validate_station_capacity,
)
from core.labs.models.resource.bench.bench import Bench
from core.labs.models.resource.bench.bench_type import BenchType
from core.labs.models.resource.location.room import Room
from core.labs.models.resource.location.room_slot import RoomSlot
from core.labs.models.resource.location.station import Station, StationStatusRecord, StationType
from core.labs.models.resource.location.station_slot import StationSlot

STATION_WRITE_FIELDS = (
    "sku", "name", "department_id", "team_id", "owner_id", "remark", "label", "type_id", "room_id", "slot_id",
    "position", "height_mm", "width_mm", "depth_mm", "orientation_degrees", "max_load_kg",
    "bench_capacity", "max_concurrent_users", "usable_surface_mm2", "power_capacity_w",
    "power_reserved_w", "cooling_capacity_w", "network_port_capacity", "utilities",
    "safety_classification",
)
PLACEMENT_FIELDS = ("room_id", "slot_id", "position", "orientation_degrees")
SLOT_WRITE_FIELDS = (
    "position_index", "slot_code", "label", "is_active", "status", "width_mm", "depth_mm",
    "height_mm", "max_load_kg", "power_capacity_w", "network_port_count", "utilities",
)

_atomic_command = atomic_command(LocationConflict)
_apply = apply_fields


def _lock_rooms(room_ids):
    ids = sorted({pk for pk in room_ids if pk is not None})
    rooms = {room.pk: room for room in Room.all_objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    if set(ids) != rooms.keys():
        raise Room.DoesNotExist
    return rooms


def _lock_station_with_rooms(station_id, data):
    preliminary_room_id = Station.objects.values_list("room_id", flat=True).get(pk=station_id)
    rooms = _lock_rooms((preliminary_room_id, data.get("room_id", preliminary_room_id)))
    station = Station.objects.select_for_update().get(pk=station_id)
    if station.room_id != preliminary_room_id:
        raise LocationConflict("The station moved concurrently; reload it and retry.")
    return station, rooms


def _check_station_unique(station):
    if Station.objects.filter(sku=station.sku.strip()).exclude(pk=station.pk).exists():
        raise LocationConflict("An active station already uses this SKU.")
    if station.slot_id is not None and Station.all_objects.filter(slot_id=station.slot_id).exclude(pk=station.pk).exists():
        raise LocationConflict("The room slot is already assigned.")


def _validate_station(station):
    # Reading bench rows is safe under the agreed station-first mutation lock.
    validate_station_capacity(
        station, list(Bench.objects.filter(setup_location_id=station.pk)) if station.pk else [],
        list(StationSlot.objects.filter(station_id=station.pk)) if station.pk else [],
    )
    _check_station_unique(station)


def _placement(station, rooms, *, old_slot_id, actor):
    ids = sorted({pk for pk in (old_slot_id, station.slot_id) if pk is not None})
    slots = {slot.pk: slot for slot in RoomSlot.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    if set(ids) != slots.keys():
        raise RoomSlot.DoesNotExist
    if station.room_id is not None:
        room = rooms[station.room_id]
        if room.deleted_at is not None:
            raise Room.DoesNotExist
        station.room = room
        validate_room_capacity(room, station, list(Station.objects.filter(room_id=room.pk).exclude(pk=station.pk)))
    if station.slot_id is not None:
        station.slot = slots[station.slot_id]
        validate_room_slot(station, station.slot, staying=old_slot_id == station.slot_id)
    _validate_station(station)
    station.save(actor=actor)
    if old_slot_id is not None and old_slot_id != station.slot_id:
        old_slot = slots[old_slot_id]
        if old_slot.status == "occupied":
            old_slot.status = "available"
            old_slot.save(actor=actor)
    if station.slot_id is not None:
        slot = slots[station.slot_id]
        if slot.status != "occupied":
            slot.status = "occupied"
            slot.save(actor=actor)
    return station


@_atomic_command
def create_station(*, actor, **data):
    station = Station()
    _apply(station, data, STATION_WRITE_FIELDS)
    rooms = _lock_rooms((station.room_id,))
    return _placement(station, rooms, old_slot_id=None, actor=actor)


@_atomic_command
def update_station(*, station_id, actor, **data):
    station, rooms = _lock_station_with_rooms(station_id, data)
    old_slot_id = station.slot_id
    _apply(station, data, STATION_WRITE_FIELDS)
    return _placement(station, rooms, old_slot_id=old_slot_id, actor=actor)


def place_station(*, station_id, actor, **data):
    if set(data) - set(PLACEMENT_FIELDS):
        raise ValidationError("Only placement fields may be changed here.")
    if not data:
        raise ValidationError("Provide at least one placement field.")
    return update_station(station_id=station_id, actor=actor, **data)


@_atomic_command
def delete_station(*, station_id, actor):
    station, _ = _lock_station_with_rooms(station_id, {})
    if Bench.objects.filter(setup_location_id=station.pk).exists():
        raise LocationConflict("Move or detach configured benches before deleting the station.")
    if has_active_placements(station_id=station.pk):
        raise LocationConflict("Move the equipment kept at this station before deleting it.")
    old_slot = None
    if station.slot_id is not None:
        old_slot = RoomSlot.objects.select_for_update().get(pk=station.slot_id)
    # The unconditional slot uniqueness constraint also covers deleted stations.
    station.slot = None
    station.room = None
    station.save(actor=actor)
    station.soft_delete(actor=actor)
    if old_slot is not None and old_slot.status == "occupied":
        old_slot.status = "available"
        old_slot.save(actor=actor)


def _slot_unique(slot):
    others = StationSlot.objects.filter(station_id=slot.station_id).exclude(pk=slot.pk)
    if others.filter(position_index=slot.position_index).exists() or others.filter(slot_code=slot.slot_code.strip().upper()).exists():
        raise LocationConflict("The station already has this slot code or position.")


def _bench_types(ids):
    ids = set(ids)
    types = list(BenchType.objects.filter(pk__in=ids).order_by("pk"))
    if ids != {item.pk for item in types}:
        raise BenchType.DoesNotExist
    return types


@_atomic_command
def create_station_slot(*, station_id, actor, compatible_bench_types=(), **data):
    station = Station.objects.select_for_update().get(pk=station_id)
    slot = StationSlot(station=station)
    _apply(slot, data, SLOT_WRITE_FIELDS)
    types = _bench_types(compatible_bench_types)
    _slot_unique(slot)
    slot.save(actor=actor)
    slot.compatible_bench_types.set(types)
    return slot


@_atomic_command
def update_station_slot(*, station_id, slot_id, actor, **data):
    station = Station.objects.select_for_update().get(pk=station_id)
    slot = StationSlot.objects.select_for_update().get(pk=slot_id, station_id=station_id)
    slot.station = station
    type_ids = data.pop("compatible_bench_types", None)
    types = _bench_types(type_ids) if type_ids is not None else list(slot.compatible_bench_types.all())
    _apply(slot, data, SLOT_WRITE_FIELDS)
    # Historical references still occupy the one-to-one field; do not invalidate them.
    bench = Bench.all_objects.filter(station_slot_id=slot.pk).first()
    if bench is not None:
        validate_occupied_slot(slot, bench, [item.pk for item in types])
    _slot_unique(slot)
    slot.save(actor=actor)
    if type_ids is not None:
        slot.compatible_bench_types.set(types)
    return slot


@_atomic_command
def delete_station_slot(*, station_id, slot_id, actor):
    Station.objects.select_for_update().get(pk=station_id)
    slot = StationSlot.objects.select_for_update().get(pk=slot_id, station_id=station_id)
    if Bench.all_objects.filter(station_slot_id=slot.pk).exists():
        raise LocationConflict("The slot is referenced by a current or historical bench.")
    slot.delete()


@_atomic_command
def record_station_status(*, station_id, actor, status, metadata=None):
    station = Station.objects.select_for_update().get(pk=station_id)
    record = StationStatusRecord(station=station, status=status, metadata={} if metadata is None else metadata)
    if not isinstance(record.metadata, dict):
        raise ValidationError({"metadata": "Metadata must be an object."})
    record.full_clean()
    record.save(actor=actor)
    return record


def _save_type(instance, name, actor):
    instance.name = name.strip()
    if StationType.objects.filter(name=instance.name).exclude(pk=instance.pk).exists():
        raise LocationConflict("The station type name already exists.")
    instance.full_clean()
    instance.save(actor=actor)
    return instance


@_atomic_command
def create_station_type(*, actor, name):
    return _save_type(StationType(), name, actor)


@_atomic_command
def update_station_type(*, type_id, actor, name=None):
    instance = StationType.objects.select_for_update().get(pk=type_id)
    return _save_type(instance, instance.name if name is None else name, actor)


@_atomic_command
def delete_station_type(*, type_id, actor):
    instance = StationType.objects.select_for_update().get(pk=type_id)
    if Station.all_objects.filter(type_id=type_id).exists():
        raise LocationConflict("The type is referenced by a current or historical station.")
    instance.delete()


__all__ = [
    "create_station", "create_station_slot", "create_station_type", "delete_station",
    "delete_station_slot", "delete_station_type", "place_station", "record_station_status",
    "update_station", "update_station_slot", "update_station_type",
]
