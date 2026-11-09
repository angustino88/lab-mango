"""Write notification intents in the caller's booking transaction, never send here."""

import hashlib
import uuid
from datetime import datetime, timedelta
from datetime import timezone as datetime_timezone

from django.conf import settings
from django.utils import timezone

from core.common.notifications import NotificationChannel, compute_dedupe_key
from core.labs.models import BenchBooking, BookingNotification

from ..contracts import BookingNotificationSnapshot

MATERIAL_FIELDS = ("creator_id", "bench_id", "starts_at", "ends_at", "status", "approval_status", "project_id")


def material_values(booking: BenchBooking) -> tuple:
    return tuple(getattr(booking, name) for name in MATERIAL_FIELDS)


def notifications_enabled(*, now: datetime) -> bool:
    cutoff = getattr(settings, "BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF", None)
    return bool(getattr(settings, "BOOKING_NOTIFICATIONS_ENABLED", False) and cutoff is not None and now >= cutoff)


def record_notification(
    *,
    booking: BenchBooking,
    kind: str,
    logical_key: str | None = None,
    now: datetime | None = None,
    equipment_id: int | None = None,
    bench_name: str | None = None,
    equipment_name: str | None = None,
    inactive_at: datetime | None = None,
) -> int:
    now = now or timezone.now()
    if not notifications_enabled(now=now) or not booking.creator_id:
        return 0
    owner = booking.creator
    if owner is None or not owner.is_active:
        return 0
    if logical_key is None and kind in {"created", "updated"}:
        state_hash = hashlib.sha256(repr(material_values(booking)).encode()).hexdigest()
        logical_key = f"{kind}:{state_hash}"
    event_key = logical_key or str(uuid.uuid4())
    event_id = uuid.uuid5(uuid.NAMESPACE_URL, f"labmango:booking:{booking.pk}:{kind}:{event_key}")
    snapshot = BookingNotificationSnapshot(
        booking_code=booking.booking_code,
        bench_id=booking.bench_id,
        starts_at=booking.starts_at.astimezone(datetime_timezone.utc).isoformat(),
        ends_at=booking.ends_at.astimezone(datetime_timezone.utc).isoformat(),
        status=booking.status,
        approval_status=booking.approval_status,
        equipment_id=equipment_id,
        bench_name=(
            bench_name
            or getattr(getattr(booking, "bench", None), "name", None)
            or getattr(getattr(booking, "bench", None), "sku", None)
        ),
        equipment_name=equipment_name,
        inactive_at=inactive_at.isoformat() if inactive_at else None,
    ).as_payload()
    expires_at = now + timedelta(days=1)
    if kind == "start":
        # End changes do not invalidate this event's durable start identity.
        # The current end is checked at send time, not frozen into its deadline.
        expires_at = booking.starts_at + timedelta(minutes=10)
    elif kind == "inactive":
        expires_at = min(booking.ends_at, now + timedelta(minutes=10))
    count = 0
    for channel in (NotificationChannel.EMAIL.value, NotificationChannel.TEAMS.value):
        if not getattr(settings, f"BOOKING_NOTIFICATIONS_{channel.upper()}_ENABLED", False):
            continue
        if channel == NotificationChannel.EMAIL.value and not owner.email.strip():
            continue
        key = compute_dedupe_key(event_id, channel, owner.pk)
        _, created = BookingNotification.objects.get_or_create(
            dedupe_key=key,
            defaults={
                "event_id": event_id,
                "booking": booking,
                "recipient": owner,
                "channel": channel,
                "kind": kind,
                "snapshot": snapshot,
                "created_at": now,
                "available_at": now,
                "expires_at": expires_at,
            },
        )
        count += int(created)
    return count
