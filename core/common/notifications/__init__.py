"""Shared notification primitives, contracts, and delivery algorithms."""

from .backoff import calculate_backoff_delay
from .contracts import (
    DeliveryOutcome,
    DeliveryState,
    NotificationChannel,
    NotificationPayload,
    OutboxLease,
)
from .dedupe import compute_dedupe_key
from .lease import (
    claim_leased_record,
    complete_leased_record,
    reap_expired_records,
    verify_lease_ownership,
)

__all__ = [
    "DeliveryOutcome",
    "DeliveryState",
    "NotificationChannel",
    "NotificationPayload",
    "OutboxLease",
    "calculate_backoff_delay",
    "claim_leased_record",
    "complete_leased_record",
    "compute_dedupe_key",
    "reap_expired_records",
    "verify_lease_ownership",
]
