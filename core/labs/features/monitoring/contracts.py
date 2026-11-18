"""Neutral, immutable observation inputs shared with agent adapters."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

# One-off snapshots an administrator pushes from the agent so new devices can be linked. They are
# evidence for linking only: never presence of an expected device, never "reporting", never alerts.
DISCOVERY_COLLECTOR_KEY = "discovery"


@dataclass(frozen=True, slots=True)
class DeviceObservation:
    observation_key: str
    interface_name: str
    state: str
    name: str = ""
    serial_number: str = ""  # reported evidence only; matching uses ``hardware_ids``
    hardware_ids: tuple[tuple[str, str], ...] = ()  # (kind, normalised value), e.g. ("pnp_id", "USB\\VID_…")


@dataclass(frozen=True, slots=True)
class DeviceObservationInput:
    computing_id: int
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


__all__ = ("DISCOVERY_COLLECTOR_KEY", "DeviceObservation", "DeviceObservationInput", "ObservationAcknowledgment")
