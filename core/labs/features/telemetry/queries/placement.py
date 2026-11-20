"""Read-only telemetry selectors."""

from collections.abc import Iterable

from core.labs.features.benches.public import bench_station_ids
from core.labs.features.equipment.public import active_bench_ids
from core.labs.features.locations.public import live_room_ids, station_room_ids
from core.labs.features.telemetry.contracts import Placement
from core.labs.models.telemetry import TelemetryTarget, TelemetryTargetType


def resolve_placement(*, target_ids: Iterable[int]) -> dict[int, Placement]:
    """Current room and station of each located target, in at most five queries for any batch size.

    Chain: equipment → open bench assignment → bench → station slot → station → room. A target is absent
    from the result when any link is missing or soft-deleted (unassigned equipment, a bench without a
    station slot, a station without a room); callers treat absence as "not located" and never guess.
    """
    rows = list(
        TelemetryTarget.objects.filter(pk__in=list(target_ids)).values(
            "pk", "target_type", "room_id", "station_id", "bench_id", "equipment_id"
        )
    )
    equipment_ids = {row["equipment_id"] for row in rows if row["target_type"] == TelemetryTargetType.EQUIPMENT}
    bench_of_equipment = active_bench_ids(equipment_ids=equipment_ids) if equipment_ids else {}

    bench_ids = {row["bench_id"] for row in rows if row["target_type"] == TelemetryTargetType.BENCH}
    bench_ids |= set(bench_of_equipment.values())
    station_of_bench = bench_station_ids(bench_ids=bench_ids) if bench_ids else {}

    station_ids = {row["station_id"] for row in rows if row["target_type"] == TelemetryTargetType.STATION}
    station_ids |= set(station_of_bench.values())
    room_of_station = station_room_ids(station_ids=station_ids) if station_ids else {}

    room_ids = {row["room_id"] for row in rows if row["target_type"] == TelemetryTargetType.ROOM}
    rooms_alive = live_room_ids(room_ids=room_ids) if room_ids else set()

    def station_placement(station_id: int | None) -> Placement | None:
        room_id = room_of_station.get(station_id) if station_id is not None else None
        return Placement(room_id=room_id, station_id=station_id) if room_id is not None else None

    placements: dict[int, Placement] = {}
    for row in rows:
        target_type = row["target_type"]
        placement: Placement | None
        if target_type == TelemetryTargetType.ROOM:
            placement = Placement(room_id=row["room_id"], station_id=None) if row["room_id"] in rooms_alive else None
        elif target_type == TelemetryTargetType.STATION:
            placement = station_placement(row["station_id"])
        elif target_type == TelemetryTargetType.BENCH:
            placement = station_placement(station_of_bench.get(row["bench_id"]))
        else:
            bench_id = bench_of_equipment.get(row["equipment_id"])
            placement = station_placement(station_of_bench.get(bench_id)) if bench_id is not None else None
        if placement is not None:
            placements[row["pk"]] = placement
    return placements


__all__ = ("resolve_placement",)
