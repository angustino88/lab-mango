"""Neutral, immutable observation inputs shared with agent adapters."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DeviceObservation:
    observation_key: str
    interface_name: str
    state: str
    name: str = ""
    serial_number: str = ""


@dataclass(frozen=True, slots=True)
class DeviceObservationInput:
    computer_id: int
    agent_key: str
    generation_key: UUID
    batch_key: UUID
    collector_key: str
    sequence: int
    collected_at: datetime
    is_complete: bool
    devices: tuple[DeviceObservation, ...]


@dataclass(frozen=True, slots=True)
class ObservationAcknowledgment:
    batch_key: UUID
    sequence: int
    disposition: str
    received_at: datetime
    is_replayed: bool = False


__all__ = ("DeviceObservation", "DeviceObservationInput", "ObservationAcknowledgment")
