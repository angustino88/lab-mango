"""Pure placement checks; callers hold the involved station locks."""

from collections.abc import Mapping

from django.core.exceptions import ValidationError

from core.labs.features.benches.exceptions import BenchConflict


def validate_utilities(required, provided):
    if not isinstance(required, Mapping) or not isinstance(provided, Mapping):
        raise ValidationError({"required_utilities": "Utilities must be an object."})
    for key, requirement in required.items():
        if requirement is None or requirement is False:
            continue
        available = provided.get(key)
        if isinstance(requirement, bool):
            satisfied = bool(available)
        elif isinstance(requirement, (int, float)):
            satisfied = isinstance(available, (int, float)) and available >= requirement
        else:
            satisfied = available == requirement
        if not satisfied:
            raise ValidationError({"required_utilities": f"Required utility is not supported: {key}."})


def validate_capacity(bench, station, other_benches):
    benches = [*other_benches, bench]
    checks = (
        ("setup_location", station.bench_capacity, len(benches)),
        ("requested_power_w", station.power_capacity_w,
         station.power_reserved_w + sum(item.requested_power_w or 0 for item in benches)),
        ("requested_load_kg", station.max_load_kg, sum(item.requested_load_kg or 0 for item in benches)),
        ("requested_cooling_w", station.cooling_capacity_w, sum(item.requested_cooling_w or 0 for item in benches)),
    )
    for field, capacity, demand in checks:
        if capacity is not None and demand > capacity:
            raise ValidationError({field: "The requested allocation exceeds station capacity."})
    validate_utilities(bench.required_utilities, station.utilities)


__all__ = ["BenchConflict", "validate_capacity", "validate_slot"]


def validate_slot(bench, slot, *, staying=False):
    if slot.station_id != bench.setup_location_id:
        raise ValidationError({"station_slot": "The slot must belong to the setup station."})
    # Occupancy (another bench on the slot) is checked by the caller under the slot lock.
    if slot.status != "in_service" and not staying:
        raise BenchConflict("The station slot is not in service.")
    for request_field, capacity_field in (
        ("requested_power_w", "power_capacity_w"), ("requested_load_kg", "max_load_kg"),
    ):
        demand, capacity = getattr(bench, request_field), getattr(slot, capacity_field)
        if demand is not None and capacity is not None and demand > capacity:
            raise ValidationError({request_field: "The requested allocation exceeds slot capacity."})
    validate_utilities(bench.required_utilities, slot.utilities)
