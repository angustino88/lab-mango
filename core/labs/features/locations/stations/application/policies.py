"""Station placement checks: pure, no ORM queries, writes, or transport dependencies.

Callers must materialize related rows under the appropriate parent locks.
"""

from collections.abc import Iterable

from django.core.exceptions import ValidationError

from core.labs.features.locations.application.policies import check_limit, validate_utilities
from core.labs.features.locations.exceptions import LocationConflict

__all__ = (
    "LocationConflict",
    "validate_station_capacity",
    "validate_occupied_slot",
    "validate_room_slot",
    "validate_room_capacity",
)


def validate_station_capacity(station, benches: Iterable, slots: Iterable = ()):
    benches = list(benches)
    check_limit("bench_capacity", station.bench_capacity, len(benches))
    check_limit(
        "power_capacity_w", station.power_capacity_w,
        station.power_reserved_w + sum(bench.requested_power_w or 0 for bench in benches),
    )
    check_limit("max_load_kg", station.max_load_kg, sum(bench.requested_load_kg or 0 for bench in benches))
    check_limit(
        "cooling_capacity_w", station.cooling_capacity_w,
        sum(bench.requested_cooling_w or 0 for bench in benches),
    )
    for slot in slots:
        if station.bench_capacity is not None and slot.position_index >= station.bench_capacity:
            raise ValidationError({"bench_capacity": "Configured slot positions must fit within bench capacity."})
    for bench in benches:
        validate_utilities(bench.required_utilities, station.utilities)


def validate_occupied_slot(slot, bench, compatible_type_ids):
    if slot.status != "in_service":
        raise LocationConflict("An occupied slot must stay in service.")
    compatible_type_ids = set(compatible_type_ids)
    if compatible_type_ids and bench.type_id not in compatible_type_ids:
        raise ValidationError({"compatible_bench_types": "The existing bench type must remain compatible."})
    check_limit("power_capacity_w", slot.power_capacity_w, bench.requested_power_w)
    check_limit("max_load_kg", slot.max_load_kg, bench.requested_load_kg)
    validate_utilities(bench.required_utilities, slot.utilities)


def validate_room_slot(station, slot, *, staying=False):
    if station.room_id is None or slot.room_id != station.room_id:
        raise ValidationError({"slot": "The assigned slot must belong to the station's room."})
    if slot.slot_type != "station":
        raise ValidationError({"slot": "The room slot must be a station position."})
    # Occupancy is Station.slot (checked by the caller and a unique constraint); this checks usability.
    if slot.status != "usable" and not staying:
        raise LocationConflict("The room slot is not usable.")
    for field in ("width_mm", "depth_mm", "max_load_kg"):
        check_limit(field, getattr(slot, field), getattr(station, field))
    requested_power = station.power_reserved_w if station.power_capacity_w is None else station.power_capacity_w
    check_limit("power_capacity_w", slot.power_capacity_w, requested_power)
    validate_utilities(station.utilities, slot.utilities)


def validate_room_capacity(room, station, other_stations):
    stations = [*other_stations, station]
    check_limit("power_capacity_w", room.power_capacity_w, sum(
        item.power_reserved_w if item.power_capacity_w is None else item.power_capacity_w for item in stations
    ))
    for field in ("cooling_capacity_w", "network_port_capacity"):
        check_limit(field, getattr(room, field), sum(getattr(item, field) or 0 for item in stations))
    check_limit("max_concurrent_users", room.max_occupancy, sum(item.max_concurrent_users or 0 for item in stations))
    if room.usable_height_m is not None:
        check_limit("height_mm", room.usable_height_m * 1000, station.height_mm)
    validate_utilities(station.utilities, room.utilities)


__all__ = [
    "LocationConflict", "validate_occupied_slot", "validate_room_capacity", "validate_room_slot",
    "validate_station_capacity",
]
