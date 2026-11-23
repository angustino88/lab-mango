"""Station writes lock rooms (sorted), then station, then slots; a room change also locks the station's
benches (PK order) last, to re-check their bookings against the new room's downtime.

Bench commands must lock old/new stations in PK order before locking benches
and validate aggregate allocations. This shared protocol serializes station
capacity reductions with bench placement/edits without nullable lock joins.
Downtime writers lock room, then stations, then benches: the same order.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from core.common.db.transactions import apply_fields, atomic_command
from core.labs.features.base.immutable import drop_unchanged_immutable_fields
from core.labs.features.equipment.public import close_placements_for_location, summarize_active_placements
from core.labs.features.locations.application.lifecycle import apply_legacy_status, apply_lifecycle, record_initial
from core.labs.features.locations.exceptions import LocationConflict
from core.labs.features.locations.stations.application.policies import (
    validate_occupied_slot,
    validate_room_capacity,
    validate_room_slot,
    validate_station_capacity,
)
from core.labs.models import ResourceChangeLog, ResourceDowntime
from core.labs.models.resource.base.availability import (
    bench_bookings_blocked_by_parents,
    booking_conflict_details,
)
from core.labs.models.resource.base.status import ResourceLifecycleStatus
from core.labs.models.resource.bench.bench import Bench
from core.labs.models.resource.bench.bench_type import BenchType
from core.labs.models.resource.location.room import Room
from core.labs.models.resource.location.room_slot import RoomSlot
from core.labs.models.resource.location.station import Station, StationStatusRecord, StationType
from core.labs.models.resource.location.station_slot import StationSlot
from core.users.public import LabsPermission, users_with_permission

FORCE_DELETE_REASON_MIN_LENGTH = 3
FORCE_DELETE_REASON_MAX_LENGTH = 500

STATION_WRITE_FIELDS = (
    "sku", "name", "department_id", "group_id", "owner_id", "remark", "label", "type_id", "room_id", "slot_id",
    "position", "height_mm", "width_mm", "depth_mm", "orientation_degrees", "max_load_kg",
    "bench_capacity", "max_concurrent_users", "usable_surface_mm2", "power_capacity_w",
    "power_reserved_w", "cooling_capacity_w", "network_port_capacity", "utilities",
    "safety_classification",
)
PLACEMENT_FIELDS = ("room_id", "slot_id", "position", "orientation_degrees")
SLOT_WRITE_FIELDS = (
    "position_index", "slot_code", "label", "status", "width_mm", "depth_mm",
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
        if room.lifecycle_status == ResourceLifecycleStatus.RETIRED:
            raise LocationConflict("The room is retired.")
        station.room = room
        validate_room_capacity(room, station, list(Station.objects.filter(room_id=room.pk).exclude(pk=station.pk)))
    if station.slot_id is not None:
        station.slot = slots[station.slot_id]
        validate_room_slot(station, station.slot, staying=old_slot_id == station.slot_id)
    _validate_station(station)
    # Slot occupancy is computed from Station.slot (unique, ``uniq`` constraint), never stored.
    station.save(actor=actor)
    return station


@_atomic_command
def create_station(*, actor, **data):
    """Create a station; ``lifecycle_status`` defaults to ``in_service`` and gets a first history record.

    Race guard: room/slot row locks plus the active-SKU and slot partial unique constraints; any
    failure rolls back the station and its initial record together.
    """
    station = Station()
    _apply(station, data, STATION_WRITE_FIELDS)
    rooms = _lock_rooms((station.room_id,))
    station = _placement(station, rooms, old_slot_id=None, actor=actor)
    record_initial(station, record_model=StationStatusRecord, record_field="station", actor=actor)
    return station


@_atomic_command
def update_station(*, station_id, actor, **data):
    station, rooms = _lock_station_with_rooms(station_id, data)
    old_slot_id = station.slot_id
    old_room_id = station.room_id
    data = drop_unchanged_immutable_fields(station, data)
    _apply(station, data, STATION_WRITE_FIELDS)
    if station.room_id is not None and station.room_id != old_room_id:
        _ensure_bookings_fit_new_room(station, rooms[station.room_id])
    return _placement(station, rooms, old_slot_id=old_slot_id, actor=actor)


def _ensure_bookings_fit_new_room(station, room):
    """A move must not put future bookings of the station's benches inside the new room's downtime."""
    bench_ids = tuple(
        Bench.objects.select_for_update()
        .filter(setup_location_id=station.pk)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    blocked = bench_bookings_blocked_by_parents(
        bench_ids=bench_ids,
        station=station,
        room=room,
        lab_operator_users=users_with_permission(LabsPermission.BENCH_BOOKING_BOOK_DURING_DOWNTIME),
    )
    if blocked:
        raise LocationConflict(
            "Bookings at this station fall in downtime of the new room. Move or cancel them first.",
            details=booking_conflict_details(bench_booking_ids=blocked),
        )


def place_station(*, station_id, actor, **data):
    if set(data) - set(PLACEMENT_FIELDS):
        raise ValidationError("Only placement fields may be changed here.")
    if not data:
        raise ValidationError("Provide at least one placement field.")
    return update_station(station_id=station_id, actor=actor, **data)


def _resource_label(sku: str | None, name: str | None, pk: int) -> str:
    sku_text = (sku or "").strip()
    name_text = (name or "").strip()
    if sku_text and name_text:
        return f"{sku_text} — {name_text}"
    return sku_text or name_text or f"#{pk}"


@_atomic_command
def delete_station(*, station_id, actor):
    station, _ = _lock_station_with_rooms(station_id, {})
    benches_qs = Bench.objects.filter(setup_location_id=station.pk)
    benches_total = benches_qs.count()
    bench_labels = (
        [_resource_label(sku, name, pk) for sku, name, pk in benches_qs.order_by("pk").values_list("sku", "name", "pk")[:5]]
        if benches_total
        else []
    )
    equipment_total, equipment_labels, equipment_categories = summarize_active_placements(station_id=station.pk, limit=5)

    if benches_total or equipment_total:
        details: dict[str, object] = {}
        if benches_total:
            details["benches_total"] = benches_total
            details["benches"] = bench_labels
        if equipment_total:
            details["equipment_total"] = equipment_total
            details["equipment"] = equipment_labels
            details["equipment_categories"] = equipment_categories
        if benches_total and equipment_total:
            message = "Move or detach configured benches and move the equipment kept at this station before deleting it."
        elif benches_total:
            message = "Move or detach configured benches before deleting the station."
        else:
            message = "Move the equipment kept at this station before deleting it."
        raise LocationConflict(message, details=details)
    if station.slot_id is not None:
        RoomSlot.objects.select_for_update().get(pk=station.slot_id)
    # The unconditional slot uniqueness constraint also covers deleted stations.
    station.slot = None
    station.room = None
    station.save(actor=actor)
    station.soft_delete(actor=actor)


def force_delete_station(*, station_id, reason, confirm=True, actor):
    """Detach child benches (preserving their lifecycle status), clear resting equipment placements, and soft-delete the station.

    Race guard: validates input before opening a transaction, then locks the parent room (if any),
    the station, its room slot, its child benches (PK order), and occupied station slots (PK order).
    Idempotency: calling again on a soft-deleted station raises ``Station.DoesNotExist`` (404).
    """
    if confirm is not True:
        raise ValidationError({"confirm": "Explicit confirmation is required to force-delete a station."})
    cleaned_reason = (reason or "").strip()
    if len(cleaned_reason) < FORCE_DELETE_REASON_MIN_LENGTH:
        raise ValidationError(
            {"reason": f"Provide a reason of at least {FORCE_DELETE_REASON_MIN_LENGTH} characters."}
        )
    if len(cleaned_reason) > FORCE_DELETE_REASON_MAX_LENGTH:
        raise ValidationError({"reason": f"Use at most {FORCE_DELETE_REASON_MAX_LENGTH} characters."})
    return _force_delete_station_tx(station_id=station_id, reason=cleaned_reason, actor=actor)


@_atomic_command
def _force_delete_station_tx(*, station_id, reason: str, actor):
    station, _ = _lock_station_with_rooms(station_id, {})
    if station.slot_id is not None:
        RoomSlot.objects.select_for_update().get(pk=station.slot_id)
    benches = list(Bench.objects.select_for_update().filter(setup_location_id=station.pk).order_by("pk"))
    slot_ids = sorted({bench.station_slot_id for bench in benches if bench.station_slot_id is not None})
    if slot_ids:
        list(StationSlot.objects.select_for_update().filter(pk__in=slot_ids).order_by("pk"))
    for bench in benches:
        bench.station_slot = None
        bench.setup_location = None
        bench.save(actor=actor)
    released_equipment = close_placements_for_location(station_id=station.pk, actor=actor)
    ResourceDowntime.objects.close_all(station, actor=actor)
    released = {"benches": len(benches), "equipment": released_equipment}
    acting_user = actor if getattr(actor, "is_authenticated", False) else None
    if acting_user is not None:
        content_type = ContentType.objects.get_for_model(station, for_concrete_model=False)
        ResourceChangeLog(
            resource_content_type=content_type,
            resource_object_id=str(station.pk),
            action=ResourceChangeLog.Action.DELETE,
            field_name="force_delete",
            old_value=None,
            new_value={"reason": reason, "released": released},
        ).save(actor=acting_user)
    station.slot = None
    station.room = None
    station.save(actor=actor)
    station.soft_delete(actor=actor)
    return {"id": station.pk, "released": released}


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


def _has_active_benches(station) -> bool:
    # Read under the station lock; bench commands lock stations before benches.
    return Bench.objects.filter(setup_location_id=station.pk).exclude(
        lifecycle_status=ResourceLifecycleStatus.RETIRED
    ).exists()


@_atomic_command
def change_station_lifecycle(*, station_id, actor, lifecycle_status=None, access_policy=None, metadata=None):
    """Set ``lifecycle_status`` and/or ``access_policy``; returns the station. Race guard: the station row lock."""
    station = Station.objects.select_for_update().get(pk=station_id)
    apply_lifecycle(
        station, record_model=StationStatusRecord, record_field="station", actor=actor,
        lifecycle_status=lifecycle_status, access_policy=access_policy, metadata=metadata,
        has_active_children=_has_active_benches(station),
    )
    return station


@_atomic_command
def record_station_status(*, station_id, actor, status, metadata=None):
    """Deprecated seven-value ``status`` write, mapped onto lifecycle, access policy and downtime (RS3)."""
    station = Station.objects.select_for_update().get(pk=station_id)
    return apply_legacy_status(
        station, record_model=StationStatusRecord, record_field="station", actor=actor, status=status,
        metadata=metadata, has_active_children=_has_active_benches(station),
    )


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
    "change_station_lifecycle", "create_station", "create_station_slot", "create_station_type", "delete_station",
    "delete_station_slot", "delete_station_type", "force_delete_station", "place_station", "record_station_status",
    "update_station", "update_station_slot", "update_station_type",
]
