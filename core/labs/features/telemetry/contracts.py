"""Neutral types shared across the telemetry boundary."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Placement:
    """The room and, when applicable, the station a telemetry target physically sits in."""

    room_id: int
    station_id: int | None


@dataclass(frozen=True, slots=True)
class TargetRef:
    """A room, station, bench or equipment item named by type and id (`{"type": "station", "id": 5}`)."""

    type: str
    id: int


__all__ = ("Placement", "TargetRef")
