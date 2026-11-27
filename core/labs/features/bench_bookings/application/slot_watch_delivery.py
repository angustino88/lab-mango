"""Deliver queued slot watch notifications: short claims, I/O outside locks, fenced completion.

Same ledger protocol as booking notifications (``notification_delivery``): one row per claim with
``SKIP LOCKED``, 120-second lease, five attempts with backoff. Web delivery writes the persisted
notification in the same transaction as the fenced completion, so it is created exactly once;
the websocket push runs after commit and is best effort.
"""

import logging
import random
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.common.notifications import (
    DeliveryOutcome,
    DeliveryState,
    NotificationChannel,
    calculate_backoff_delay,
    claim_leased_record,
    complete_leased_record,
    reap_expired_records,
    verify_lease_ownership,
)
from core.labs.models import BenchBooking, BenchSlotNotification, SlotWatchKind, SlotWatchStatus
from core.users.public import resolve_teams_recipient
from core.websocket.models import Notification
from core.websocket.publish_service import publish_user_notification

from ..integrations.slot_watch_transport import send_slot_email, send_slot_teams, web_expiry, web_message
from .slot_watch_collection import channel_enabled, is_reserving, slot_still_free

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
LEASE_SECONDS = 120


FOLLOW_KINDS = frozenset({SlotWatchKind.BOOKING_ENDING_SOON.value, SlotWatchKind.BOOKING_RELEASED.value})


def follow_still_current(*, row: BenchSlotNotification) -> bool:
    """An "ending soon" alert is stale if the booking was extended; a release alert is always news."""
    if row.kind != SlotWatchKind.BOOKING_ENDING_SOON.value:
        return True
    booking = BenchBooking.objects.only("status", "approval_status", "ends_at").get(pk=row.booking_id)
    if not is_reserving(booking):
        return True  # ended even sooner: still worth telling
    return booking.ends_at == datetime.fromisoformat(row.snapshot["free_from"])


class _Fenced(Exception):
    """Another worker owns the row now; roll back the web notification."""


def precheck(*, row: BenchSlotNotification, now: datetime) -> DeliveryOutcome | None:
    if row.expires_at <= now:
        return DeliveryOutcome("expired", "expired")
    if not channel_enabled(row.channel):
        return DeliveryOutcome("skipped", "channel_disabled")
    watch = row.watch
    is_follow = row.kind in FOLLOW_KINDS
    # A follow is marked fulfilled when its single alert is queued; a range watch must still be active.
    live = (SlotWatchStatus.ACTIVE, SlotWatchStatus.FULFILLED) if is_follow else (SlotWatchStatus.ACTIVE,)
    if watch.status not in live or watch.user_id != row.recipient_id or (not is_follow and watch.range_end <= now):
        return DeliveryOutcome("skipped", "watch_inactive")
    if not row.recipient.is_active:
        return DeliveryOutcome("skipped", "recipient_unavailable")
    if row.channel == NotificationChannel.EMAIL.value and not (row.recipient.email or "").strip():
        return DeliveryOutcome("skipped", "recipient_unavailable")
    if is_follow:
        return None if follow_still_current(row=row) else DeliveryOutcome("expired", "booking_changed")
    if not slot_still_free(
        bench_id=row.snapshot["bench_id"],
        free_from=datetime.fromisoformat(row.snapshot["free_from"]),
        free_until=datetime.fromisoformat(row.snapshot["free_until"]),
        now=now,
    ):
        return DeliveryOutcome("expired", "slot_taken")
    return None


def _complete(row: BenchSlotNotification, result: DeliveryOutcome, now: datetime) -> bool:
    backoff = None
    if result.state == "retry" and row.attempts < MAX_ATTEMPTS:
        backoff = calculate_backoff_delay(attempt=row.attempts, jitter=random.random())
    return complete_leased_record(
        BenchSlotNotification.objects,
        row=row,
        outcome=result,
        now=now,
        max_attempts=MAX_ATTEMPTS,
        backoff_delay=backoff,
    )


def _deliver_web(row: BenchSlotNotification) -> bool:
    """Create the feed entry and complete the claim atomically; push after commit."""
    now = timezone.now()
    message, details, action_path = web_message(kind=row.kind, snapshot=row.snapshot)
    try:
        with transaction.atomic():
            notification = Notification.objects.create(
                target_user_id=row.recipient_id,
                message=message,
                details=details,
                message_type=Notification.SUCCESS,
                expiry_date=web_expiry(snapshot=row.snapshot, now=now),
                action_path=action_path,
            )
            if not _complete(row, DeliveryOutcome("sent", "accepted"), now):
                raise _Fenced
            transaction.on_commit(
                lambda: publish_user_notification(
                    row.recipient_id,
                    message,
                    message_type=Notification.SUCCESS,
                    details=details,
                    notification_id=notification.pk,
                    action_path=action_path,
                )
            )
    except _Fenced:
        return False
    return True


def _send(row: BenchSlotNotification) -> DeliveryOutcome:
    if row.channel == NotificationChannel.EMAIL.value:
        return send_slot_email(
            recipient=row.recipient.email.strip(), kind=row.kind, snapshot=row.snapshot, event_id=row.event_id
        )
    teams_recipient = resolve_teams_recipient(
        user_id=row.recipient_id,
        expected_tenant_id=getattr(settings, "BOOKING_NOTIFICATIONS_TEAMS_EXPECTED_TENANT_ID", None),
    )
    if teams_recipient is None:
        return DeliveryOutcome("skipped", "teams_identity_unavailable")
    return send_slot_teams(
        kind=row.kind, snapshot=row.snapshot, event_id=row.event_id, teams_recipient=teams_recipient
    )


def deliver_slot_watch_notifications(*, limit: int = 10) -> dict[str, int]:
    counts = {"claimed": 0, "sent": 0, "failed": 0, "retry": 0, "skipped": 0, "expired": 0, "fenced": 0}
    counts["expired"] += reap_expired_records(
        BenchSlotNotification.objects, now=timezone.now(), transaction=transaction
    )
    for _ in range(min(max(limit, 1), 10)):
        now = timezone.now()
        row = claim_leased_record(
            BenchSlotNotification.objects,
            now=now,
            lease_seconds=LEASE_SECONDS,
            max_attempts=MAX_ATTEMPTS,
            transaction=transaction,
        )
        if row is None:
            break
        counts["claimed"] += 1
        if row.state != DeliveryState.LEASED.value:
            counts[row.state] += 1
            continue
        token = row.lease_token
        row = BenchSlotNotification.objects.select_related("watch", "recipient").get(pk=row.pk)
        if not verify_lease_ownership(row, token=token, now=timezone.now()):
            counts["fenced"] += 1
            continue
        result = precheck(row=row, now=timezone.now())
        if result is None and row.channel == NotificationChannel.IN_APP.value:
            counts["sent" if _deliver_web(row) else "fenced"] += 1
            continue
        if result is None:
            result = _send(row)
        if _complete(row, result, timezone.now()):
            state = result.state
            if state == "retry" and row.attempts >= MAX_ATTEMPTS:
                state = DeliveryState.FAILED.value
            counts[state] += 1
            logger.info("slot_watch_delivery channel=%s state=%s outcome=%s", row.channel, state, result.code)
        else:
            counts["fenced"] += 1
    logger.info("slot_watch_delivery_batch counts=%s", counts)
    return counts
