"""Current environment and power per room and station, from each channel's latest reading."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from core.labs.models.telemetry import TelemetryLatest, TelemetryReadingStatus

from .placement import resolve_placement

#: A reading older than this is not "current": dashboards show no data instead of a stale value.
FRESH_FOR = timedelta(minutes=15)
METRICS = ("temperature_c", "humidity_percent", "power_w")


@dataclass(frozen=True, slots=True)
class CurrentConditions:
    temperature_c: float | None
    humidity_percent: float | None
    power_w: float | None
    observed_at: datetime | None
    channel_count: int


def _summarise(rows) -> CurrentConditions:
    by_metric: dict[str, list[float]] = {metric: [] for metric in METRICS}
    for row in rows:
        by_metric[row["metric_id"]].append(float(row["value"]))

    def mean(values):
        return round(sum(values) / len(values), 2) if values else None

    power = by_metric["power_w"]
    return CurrentConditions(
        temperature_c=mean(by_metric["temperature_c"]),
        humidity_percent=mean(by_metric["humidity_percent"]),
        power_w=round(sum(power), 1) if power else None,
        observed_at=max((row["observed_at"] for row in rows), default=None),
        channel_count=len(rows),
    )


def current_conditions(*, room_ids=(), station_ids=()) -> dict[str, dict[int, CurrentConditions]]:
    """Mean temperature and humidity and total power of fresh readings placed in each room and station.

    Readings roll up through placement (equipment → bench → station → room), so a sensor on a bench counts for
    its station and room. Two to six queries whatever the number of rooms and stations.
    """
    rooms, stations = set(room_ids), set(station_ids)
    if not rooms and not stations:
        return {"rooms": {}, "stations": {}}
    rows = list(
        TelemetryLatest.objects.filter(
            metric_id__in=METRICS,
            status=TelemetryReadingStatus.OK,
            observed_at__gte=timezone.now() - FRESH_FOR,
        ).values("target_id", "metric_id", "value", "observed_at")
    )
    placements = resolve_placement(target_ids={row["target_id"] for row in rows}) if rows else {}
    per_room: dict[int, list[Any]] = {}
    per_station: dict[int, list[Any]] = {}
    for row in rows:
        placement = placements.get(row["target_id"])
        if placement is None:
            continue
        if placement.room_id in rooms:
            per_room.setdefault(placement.room_id, []).append(row)
        if placement.station_id is not None and placement.station_id in stations:
            per_station.setdefault(placement.station_id, []).append(row)
    return {
        "rooms": {room_id: _summarise(items) for room_id, items in per_room.items()},
        "stations": {station_id: _summarise(items) for station_id, items in per_station.items()},
    }
