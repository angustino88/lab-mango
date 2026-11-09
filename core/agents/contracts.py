"""Neutral immutable inputs for agent identity operations."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CreateEnrollmentGrantInput:
    equipment_uid: UUID
    ttl_minutes: int


@dataclass(frozen=True, slots=True)
class EnrollmentGrantIssued:
    agent_uid: UUID
    equipment_uid: UUID
    grant: str
    expires_at: datetime
