"""Short row claims, I/O outside transactions, and token-fenced completion."""

import logging
import random
import uuid
from datetime import datetime, timedelta
from time import monotonic

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.common.notifications import (
    DeliveryOutcome,
    DeliveryState,
    calculate_backoff_delay,
    claim_leased_record,
    complete_leased_record,
    reap_expired_records,
    verify_lease_ownership,
)
from core.labs.features.equipment.public import inactive_equipment_candidates
from core.labs.models import BookingApprovalStatus, BookingNotification, BookingStatus
from core.users.public import resolve_teams_recipient

from ..contracts import BookingNotificationSnapshot
from ..integrations.notification_transport import deliver
from .notification_collection import start_eligible
from .notification_intents import notifications_enabled

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
LEASE_SECONDS = 120


def retry_delay(*, attempt: int, jitter: float) -> timedelta:
    return calculate_backoff_delay(attempt=attempt, jitter=jitter)


def claim_one(*, now: datetime) -> BookingNotification | None:
    return claim_leased_record(
        BookingNotification.objects,
        now=now,
        lease_seconds=LEASE_SECONDS,
        max_attempts=MAX_ATTEMPTS,
        transaction=transaction,
    )


def reminder_is_current(*, row: BookingNotification, now: datetime) -> bool:
    booking = row.booking
    if row.kind == "inactive" and (
        booking.starts_at != datetime.fromisoformat(row.snapshot["starts_at"])
        or booking.ends_at != datetime.fromisoformat(row.snapshot["ends_at"])
        or booking.bench_id != row.snapshot["bench_id"]
    ):
        return False
    if row.kind == "start":
        return (
            start_eligible(booking=booking, now=now)
            and booking.starts_at == datetime.fromisoformat(row.snapshot["starts_at"])
            and booking.bench_id == row.snapshot["bench_id"]
        )
    if row.kind == "inactive":
        cutoff = settings.BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF
        if cutoff is None:
            return False
        candidates = inactive_equipment_candidates(now=now, equipment_id=row.snapshot["equipment_id"], limit=1)
        if not candidates:
            return False
        candidate = candidates[0]
        return (
            booking.status == BookingStatus.IN_PROGRESS
            and booking.approval_status == BookingApprovalStatus.APPROVED
            and booking.starts_at <= now < booking.ends_at
            and candidate.booking_code == booking.booking_code
            and candidate.bench_id == booking.bench_id
            and candidate.inactive_at.isoformat() == row.snapshot["inactive_at"]
            and candidate.inactive_at >= booking.starts_at
            and candidate.inactive_at >= cutoff
        )
    return True


def delivery_precheck(*, row: BookingNotification, now: datetime) -> DeliveryOutcome | None:
    cutoff = settings.BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF
    if cutoff is None or row.expires_at <= now or row.created_at < cutoff:
        return DeliveryOutcome("expired", "expired")
    if not getattr(settings, f"BOOKING_NOTIFICATIONS_{row.channel.upper()}_ENABLED", False):
        return DeliveryOutcome("skipped", "channel_disabled")
    if row.recipient_id != row.booking.creator_id or not row.recipient.is_active:
        return DeliveryOutcome("skipped", "recipient_unavailable")
    if row.channel == "email" and not row.recipient.email.strip():
        return DeliveryOutcome("skipped", "recipient_unavailable")
    if not reminder_is_current(row=row, now=now):
        return DeliveryOutcome("expired", "reminder_obsolete")
    return None


def reap_expired(*, now: datetime, limit: int = 100) -> int:
    """Bounded cleanup independent of reminder transport capacity; never touch active leases."""
    return reap_expired_records(
        BookingNotification.objects,
        now=now,
        limit=limit,
        transaction=transaction,
    )


def owns_lease(*, row: BookingNotification, token: uuid.UUID | None, now: datetime) -> bool:
    return BookingNotification.objects.filter(
        pk=row.pk,
        state=DeliveryState.LEASED.value,
        lease_token=token,
        lease_until__gt=now,
    ).exists()


def send_snapshot(row: BookingNotification) -> BookingNotificationSnapshot:
    if row.kind != "start":
        return BookingNotificationSnapshot(**row.snapshot)
    booking = row.booking
    current = BookingNotificationSnapshot(
        booking_code=booking.booking_code,
        bench_id=booking.bench_id,
        starts_at=booking.starts_at.isoformat(),
        ends_at=booking.ends_at.isoformat(),
        status=booking.status,
        approval_status=booking.approval_status,
        bench_name=getattr(getattr(booking, "bench", None), "name", None)
        or getattr(getattr(booking, "bench", None), "sku", None),
    )
    merged = row.snapshot | current.as_payload()
    merged["equipment_id"] = row.snapshot.get("equipment_id")
    merged["equipment_name"] = row.snapshot.get("equipment_name")
    merged["inactive_at"] = row.snapshot.get("inactive_at")
    return BookingNotificationSnapshot(**merged)


def complete_claim(*, row: BookingNotification, result: DeliveryOutcome, now: datetime) -> bool:
    state = result.state
    if state == "retry":
        state = DeliveryState.PENDING.value if row.attempts < MAX_ATTEMPTS else DeliveryState.FAILED.value
    backoff = retry_delay(attempt=row.attempts, jitter=random.random()) if state == DeliveryState.PENDING.value else None
    changed = complete_leased_record(
        BookingNotification.objects,
        row=row,
        outcome=result,
        now=now,
        max_attempts=MAX_ATTEMPTS,
        backoff_delay=backoff,
    )
    if changed:
        logger.log(
            logging.WARNING if state == DeliveryState.FAILED.value else logging.INFO,
            "booking_notification_delivery channel=%s state=%s outcome=%s",
            row.channel,
            state,
            result.code,
        )
    return bool(changed)


def deliver_notifications(*, limit: int = 5) -> dict[str, int]:
    counts = {"claimed": 0, "sent": 0, "failed": 0, "retry": 0, "skipped": 0, "expired": 0, "fenced": 0}
    if not notifications_enabled(now=timezone.now()):
        return counts
    counts["expired"] += reap_expired(now=timezone.now())
    for _ in range(min(max(limit, 1), 5)):
        now = timezone.now()
        if not notifications_enabled(now=now):
            break
        row = claim_one(now=now)
        if row is None:
            break
        counts["claimed"] += 1
        if row.state != DeliveryState.LEASED.value:
            counts[row.state] += 1
            continue
        # Fresh related reads occur after releasing the claim lock.
        token = row.lease_token
        row = BookingNotification.objects.select_related("booking", "recipient").get(pk=row.pk)
        # Another worker cannot own an unexpired lease, but verify the lease before I/O.
        if not verify_lease_ownership(row, token=token, now=timezone.now()):
            counts["fenced"] += 1
            continue
        result = delivery_precheck(row=row, now=timezone.now())
        teams_recipient = None
        if result is None and row.channel == "teams":
            teams_recipient = resolve_teams_recipient(
                user_id=row.recipient_id,
                expected_tenant_id=settings.BOOKING_NOTIFICATIONS_TEAMS_EXPECTED_TENANT_ID,
            )
            if teams_recipient is None:
                result = DeliveryOutcome("skipped", "teams_identity_unavailable")
        if result is None:
            snapshot = send_snapshot(row)
            # Prechecks/projections can be slow. Re-read the fence and clock just before I/O.
            now = timezone.now()
            if not owns_lease(row=row, token=token, now=now):
                counts["fenced"] += 1
                continue
            now = timezone.now()
            if row.expires_at <= now or not reminder_is_current(row=row, now=now):
                result = DeliveryOutcome("expired", "expired")
        if result is None:
            started = monotonic()
            result = deliver(
                channel=row.channel,
                recipient=row.recipient.email.strip(),
                event_id=row.event_id,
                kind=row.kind,
                snapshot=snapshot,
                teams_recipient=teams_recipient,
            )
            logger.info(
                "booking_notification_transport channel=%s outcome=%s duration_seconds=%.3f",
                row.channel,
                result.code,
                monotonic() - started,
            )
        if complete_claim(row=row, result=result, now=timezone.now()):
            counts["failed" if result.state == "retry" and row.attempts >= MAX_ATTEMPTS else result.state] += 1
        else:
            counts["fenced"] += 1
    logger.info("booking_notification_batch counts=%s", counts)
    return counts
