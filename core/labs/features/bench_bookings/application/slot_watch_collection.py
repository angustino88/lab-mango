"""Find slot watches whose bench is opening up and queue one notification per event and channel.

Two events, both about a booking that overlaps the watched range on the same bench:

* ``slot_ending_soon`` — a reserving booking ends within the lead time (default 15 minutes)
  and leaves free time inside the range right after it ends.
* ``slot_freed`` — a booking stopped reserving the bench (cancelled, expired, rejected, or
  completed before its booked end) after the watch was created, leaving free time in the range.

"Free time" means a gap of at least ``MIN_FREE_GAP`` not covered by any other reserving booking.
The job is bounded (keyset pages of 100 watches) and repeatable: dedupe keys make a second run
over the same state insert nothing. It holds no lock while it reads; inserts are single rows.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.db import transaction
from django.db.models import Q

from core.common.notifications import NotificationChannel, compute_dedupe_key
from core.labs.models import (
    BenchBooking,
    BenchSlotNotification,
    BenchSlotWatch,
    Booking,
    BookingApprovalStatus,
    BookingStatus,
    SlotWatchKind,
    SlotWatchStatus,
)

MIN_FREE_GAP = timedelta(minutes=5)
RELEASE_LOOKBACK = timedelta(minutes=15)
NOTICE_LIFETIME = timedelta(minutes=30)
PAGE_SIZE = 100
BOOKINGS_PER_WATCH = 200

Interval = tuple[datetime, datetime]


def slot_watch_enabled() -> bool:
    return bool(getattr(settings, "BOOKING_SLOT_WATCH_ENABLED", False))


def channel_enabled(channel: str) -> bool:
    """Web needs only the slot watch flag; email/Teams reuse the booking notification switches."""
    if not slot_watch_enabled():
        return False
    if channel == NotificationChannel.IN_APP.value:
        return True
    return bool(
        getattr(settings, "BOOKING_NOTIFICATIONS_ENABLED", False)
        and getattr(settings, f"BOOKING_NOTIFICATIONS_{channel.upper()}_ENABLED", False)
    )


def free_intervals(window: Interval, busy: list[Interval], *, min_gap: timedelta = MIN_FREE_GAP) -> list[Interval]:
    """Half-open gaps in ``window`` not covered by ``busy``, each at least ``min_gap`` long."""
    lo, hi = window
    gaps: list[Interval] = []
    cursor = lo
    for start, end in sorted(busy):
        if end <= cursor:
            continue
        if start >= hi:
            break
        if start > cursor:
            gaps.append((cursor, min(start, hi)))
        cursor = max(cursor, end)
        if cursor >= hi:
            break
    if cursor < hi:
        gaps.append((cursor, hi))
    return [(s, e) for s, e in gaps if e - s >= min_gap]


def is_reserving(booking: BenchBooking) -> bool:
    return booking.status in Booking.ACTIVE_STATUSES and booking.approval_status in Booking.RESERVING_APPROVAL_STATUSES


@dataclass(frozen=True, slots=True)
class SlotEvent:
    kind: str
    booking_id: int
    logical_key: str
    free_from: datetime
    free_until: datetime


def _released_from(booking: BenchBooking) -> datetime:
    """Where the booking's hold on the bench ended: early completion frees time from completion."""
    if booking.status == BookingStatus.COMPLETED and booking.completed_at and booking.completed_at < booking.ends_at:
        return max(booking.starts_at, booking.completed_at)
    return booking.starts_at


def evaluate_watch(*, watch: BenchSlotWatch, bookings: list[BenchBooking], now: datetime) -> list[SlotEvent]:
    """Pure decision: the events this watch should hear about given the bench's overlapping bookings."""
    lo, hi = max(watch.range_start, now), watch.range_end
    if lo >= hi:
        return []
    lead = timedelta(minutes=getattr(settings, "BOOKING_SLOT_WATCH_LEAD_MINUTES", 15))
    reserving = [b for b in bookings if is_reserving(b)]
    events: list[SlotEvent] = []
    for booking in bookings:
        if booking.creator_id == watch.user_id:
            continue  # The watcher's own booking is not news to them.
        others = [(b.starts_at, b.ends_at) for b in reserving if b.pk != booking.pk]
        if booking in reserving:
            if not (now < booking.ends_at <= now + lead and booking.ends_at < hi):
                continue
            gaps = free_intervals((booking.ends_at, hi), others)
            if gaps and gaps[0][0] == booking.ends_at:
                events.append(
                    SlotEvent(
                        kind=SlotWatchKind.ENDING_SOON.value,
                        booking_id=booking.pk,
                        logical_key=booking.ends_at.astimezone(dt_timezone.utc).isoformat(),
                        free_from=gaps[0][0],
                        free_until=gaps[0][1],
                    )
                )
            continue
        if booking.modified < max(watch.created, now - RELEASE_LOOKBACK):
            continue
        released = (max(_released_from(booking), lo), min(booking.ends_at, hi))
        if released[0] >= released[1]:
            continue
        gaps = free_intervals(released, others)
        if gaps:
            events.append(
                SlotEvent(
                    kind=SlotWatchKind.FREED.value,
                    booking_id=booking.pk,
                    logical_key="released",
                    free_from=gaps[0][0],
                    free_until=gaps[0][1],
                )
            )
    return events


def overlapping_bookings(*, bench_id: int, window: Interval) -> list[BenchBooking]:
    lo, hi = window
    return list(
        BenchBooking.objects.filter(bench_id=bench_id, starts_at__lt=hi, ends_at__gt=lo)
        .only(
            "pk",
            "bench_id",
            "creator_id",
            "starts_at",
            "ends_at",
            "status",
            "approval_status",
            "completed_at",
            "modified",
        )
        .order_by("starts_at", "pk")[:BOOKINGS_PER_WATCH]
    )


def snapshot_for(*, watch: BenchSlotWatch, event: SlotEvent) -> dict:
    """Allowlisted facts only: never the other user's identity, booking code or reason."""
    bench = watch.bench
    return {
        "watch_id": watch.pk,
        "bench_id": watch.bench_id,
        "bench_name": bench.name or bench.sku,
        "range_start": _iso(watch.range_start),
        "range_end": _iso(watch.range_end),
        "free_from": _iso(event.free_from),
        "free_until": _iso(event.free_until),
    }


def _iso(value: datetime) -> str:
    return value.astimezone(dt_timezone.utc).isoformat()


def record_events(*, watch: BenchSlotWatch, events: list[SlotEvent], now: datetime) -> int:
    created = 0
    for event in events:
        for channel in watch.channels():
            if not channel_enabled(channel):
                continue
            if channel == NotificationChannel.EMAIL.value and not (watch.user.email or "").strip():
                continue
            event_id = uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"labmango:slot-watch:{watch.pk}:{event.kind}:{event.booking_id}:{event.logical_key}",
            )
            key = compute_dedupe_key(event_id, channel, watch.user_id)
            with transaction.atomic():
                _, was_created = BenchSlotNotification.objects.get_or_create(
                    dedupe_key=key,
                    defaults={
                        "event_id": event_id,
                        "recipient_id": watch.user_id,
                        "watch": watch,
                        "booking_id": event.booking_id,
                        "channel": channel,
                        "kind": event.kind,
                        "snapshot": snapshot_for(watch=watch, event=event),
                        "created_at": now,
                        "available_at": now,
                        "expires_at": min(event.free_until, now + NOTICE_LIFETIME),
                    },
                )
            created += int(was_created)
    return created


def expire_finished_watches(*, now: datetime, limit: int = 500) -> int:
    ids = list(
        BenchSlotWatch.objects.filter(status=SlotWatchStatus.ACTIVE, range_end__lte=now)
        .order_by("pk")
        .values_list("pk", flat=True)[:limit]
    )
    if not ids:
        return 0
    return BenchSlotWatch.objects.filter(pk__in=ids, status=SlotWatchStatus.ACTIVE).update(
        status=SlotWatchStatus.EXPIRED, modified=now
    )


def collect_slot_watch_notifications(*, now: datetime, after_watch_id: int = 0) -> dict[str, int]:
    """One bounded page. ``cursor`` is the next ``after_watch_id``, or -1 when the scan is done."""
    if not slot_watch_enabled():
        return {"created": 0, "expired_watches": 0, "cursor": -1}
    expired = expire_finished_watches(now=now) if after_watch_id == 0 else 0
    watches = list(
        BenchSlotWatch.objects.filter(
            Q(user__is_active=True),
            pk__gt=after_watch_id,
            status=SlotWatchStatus.ACTIVE,
            range_end__gt=now,
            range_start__lt=now + timedelta(days=1),  # nothing can be "ending soon" further out
        )
        .select_related("user", "bench")
        .order_by("pk")[:PAGE_SIZE]
    )
    created = 0
    for watch in watches:
        window = (max(watch.range_start, now), watch.range_end)
        if window[0] >= window[1]:
            continue
        # Bookings that started before the window still matter when they end inside it.
        bookings = overlapping_bookings(bench_id=watch.bench_id, window=window)
        events = evaluate_watch(watch=watch, bookings=bookings, now=now)
        if events:
            created += record_events(watch=watch, events=events, now=now)
    cursor = watches[-1].pk if len(watches) == PAGE_SIZE else -1
    return {"created": created, "expired_watches": expired, "cursor": cursor}


def slot_still_free(*, bench_id: int, free_from: datetime, free_until: datetime, now: datetime) -> bool:
    """Send-time revalidation: is there still a usable gap where the notice says?"""
    lo = max(free_from, now)
    if free_until - lo < MIN_FREE_GAP:
        return False
    reserving = [
        (b.starts_at, b.ends_at)
        for b in BenchBooking.objects.filter(
            bench_id=bench_id,
            starts_at__lt=free_until,
            ends_at__gt=lo,
            status__in=(BookingStatus.RESERVED, BookingStatus.IN_PROGRESS),
            approval_status__in=(BookingApprovalStatus.PENDING, BookingApprovalStatus.APPROVED),
        ).only("starts_at", "ends_at")[:BOOKINGS_PER_WATCH]
    ]
    return bool(free_intervals((lo, free_until), reserving))
