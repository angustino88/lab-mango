"""Frozen inputs and outputs of the license-check intake (agents app → this feature)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class ReportedLicense:
    """One license as the agent's check read it. Never contains license keys or raw tool output."""

    observation_key: str
    product_name: str
    carrier_type: str
    vendor: str = ""
    product_code: str = ""
    license_serial: str = ""
    carrier_hardware_kind: str = ""
    carrier_hardware_value: str = ""
    carrier_equipment_uid: str = ""
    expires_at: datetime | None = None
    final_expires_at: datetime | None = None
    max_version: str = ""
    is_reactivatable: bool = False


@dataclass(frozen=True)
class LicenseCheckRunInput:
    """One run. ``computing_id`` and ``agent_uid`` come from the signing identity, never the body."""

    computing_id: int
    agent_uid: UUID
    check_key: str
    idempotency_key: UUID
    revision: int
    sequence: int
    status: str
    started_at: datetime
    duration_ms: int = 0
    is_complete: bool = False
    error_code: str = ""
    error_message: str = ""
    licenses: tuple[ReportedLicense, ...] = ()


@dataclass(frozen=True)
class LicenseCheckRunAcknowledgment:
    """``result``: ``applied``, ``recorded`` (not ok: run kept, licenses unchanged), ``stale``
    (older sequence) or ``outdated_revision`` (the check changed since the agent fetched it)."""

    idempotency_key: UUID
    sequence: int
    result: str
    received_at: datetime
    is_replayed: bool = False


__all__ = ("ReportedLicense", "LicenseCheckRunInput", "LicenseCheckRunAcknowledgment")
