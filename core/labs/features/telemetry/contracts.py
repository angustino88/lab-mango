"""Neutral types shared across the telemetry boundary."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Placement:
    """The room and, when applicable, the station a telemetry target physically sits in."""

    room_id: int
    station_id: int | None


__all__ = ("Placement",)
