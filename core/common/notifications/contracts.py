"""Standard contracts and data transfer objects for notification delivery."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID


class NotificationChannel(str, Enum):
    """Supported delivery channels."""

    EMAIL = "email"
    TEAMS = "teams"
    IN_APP = "in_app"


class DeliveryState(str, Enum):
    """Lifecycle states for notification outbox records."""

    PENDING = "pending"
    LEASED = "leased"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    """Sanitized transport outcome for ledger state updates."""

    state: str
    code: str


@dataclass(frozen=True, slots=True)
class OutboxLease:
    """Active concurrency lease held by a delivery worker."""

    token: UUID
    until: datetime


@dataclass(frozen=True, slots=True)
class NotificationPayload:
    """Structured payload for rendering and dispatching notifications."""

    channel: NotificationChannel | str
    recipient_id: int | str
    subject: str = ""
    text: str = ""
    template: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    deep_link: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
