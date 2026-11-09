"""Neutral DTOs, protocols, and event types shared across equipment boundaries."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class InactiveEquipmentSnapshot:
    equipment_id: int
    bench_id: int
    booking_code: str
    inactive_at: datetime
    assigned_at: datetime
    bench_name: str | None = None
    equipment_name: str | None = None


@dataclass(frozen=True, slots=True)
class ActiveEquipmentBenchAssignment:
    equipment_id: int
    bench_id: int


__all__ = ("ActiveEquipmentBenchAssignment", "InactiveEquipmentSnapshot")
