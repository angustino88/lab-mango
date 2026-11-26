"""Find slot watches whose bench is opening up and queue one notification per event and channel.

Two events, both about a booking that overlaps the watched range on the same bench:

* ``slot_ending_soon`` — a reserving booking ends within the lead time (default 15 minutes)
  and leaves free time inside the range right after it ends.
* ``slot_freed`` — a booking stopped reserving the bench (cancelled, expired, rejected, or
  completed before its booked end) after the watch was created, leaving free time in the range.

Booking follows (``target_booking`` set) get exactly one alert, whichever comes first:

* ``booking_ending_soon`` — the followed booking still reserves the bench and ends within the lead time;
* ``booking_released`` — it completed (early or on time), or was cancelled, expired or rejected after the
  follow started.

Recording that alert and marking the watch ``fulfilled`` happen in one transaction under a row lock on the
watch, so concurrent or repeated runs cannot send a second alert. While the booking is extended, the
watch's ``range_end`` follows its current end.

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
    SlotWatchChannel,
    SlotWatchKind,
    SlotWatchStatus,
)

MIN_FREE_GAP = timedelta(minutes=5)
RELEASE_LOOKBACK = timedelta(minutes=15)
FOLLOW_RELEASE_LOOKBACK = timedelta(days=1)
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
    free_until: datetime | None


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


def next_reserving_start(*, bench_id: int, after: datetime, exclude_id: int) -> datetime | None:
    """Start of the next booking that will take the bench at or after ``after`` (within a day)."""
    booking = (
        BenchBooking.objects.filter(
            bench_id=bench_id,
            ends_at__gt=after,
            starts_at__lt=after + timedelta(days=1),
            status__in=(BookingStatus.RESERVED, BookingStatus.IN_PROGRESS),
            approval_status__in=(BookingApprovalStatus.PENDING, BookingApprovalStatus.APPROVED),
        )
        .exclude(pk=exclude_id)
        .order_by("starts_at")
        .only("starts_at")
        .first()
    )
    return max(booking.starts_at, after) if booking else None


def evaluate_follow(*, watch: BenchSlotWatch, booking: BenchBooking, now: datetime) -> SlotEvent | None:
    """Pure-ish decision for a followed booking: the one alert to send now, if any."""
    lead = timedelta(minutes=getattr(settings, "BOOKING_SLOT_WATCH_LEAD_MINUTES", 15))
    if is_reserving(booking):
        if not now < booking.ends_at <= now + lead:
            return None
        kind, key, free_from = (
            SlotWatchKind.BOOKING_ENDING_SOON.value,
            booking.ends_at.astimezone(dt_timezone.utc).isoformat(),
            booking.ends_at,
        )
    else:
        if booking.modified < max(watch.created, now - FOLLOW_RELEASE_LOOKBACK):
            return None
        kind, key, free_from = SlotWatchKind.BOOKING_RELEASED.value, "released", max(now, _released_from(booking))
    free_until = next_reserving_start(bench_id=booking.bench_id, after=free_from, exclude_id=booking.pk)
    return SlotEvent(kind=kind, booking_id=booking.pk, logical_key=key, free_from=free_from, free_until=free_until)


def collect_follow(*, watch: BenchSlotWatch, now: datetime) -> tuple[int, bool]:
    """Evaluate one booking follow. Returns (rows created, watch closed)."""
    booking = watch.target_booking
    if booking is None:
        return 0, False
    event = evaluate_follow(watch=watch, booking=booking, now=now)
    if event is None:
        if not is_reserving(booking):
            # Released before the follow started, or longer ago than we backfill: nothing left to say.
            closed = BenchSlotWatch.objects.filter(pk=watch.pk, status=SlotWatchStatus.ACTIVE).update(
                status=SlotWatchStatus.EXPIRED, modified=now
            )
            return 0, bool(closed)
        if booking.ends_at != watch.range_end and booking.ends_at > watch.range_start:
            # Extended or shortened: keep following the booking's current end.
            BenchSlotWatch.objects.filter(pk=watch.pk, status=SlotWatchStatus.ACTIVE).update(
                range_end=booking.ends_at, modified=now
            )
        return 0, False
    with transaction.atomic():
        # One-shot guard: only the run that still sees the follow active records the alert.
        locked = BenchSlotWatch.objects.select_for_update().filter(pk=watch.pk, status=SlotWatchStatus.ACTIVE).first()
        if locked is None:
            return 0, False
        created = record_events(watch=watch, events=[event], now=now)
        locked.status = SlotWatchStatus.FULFILLED
        locked.save(update_fields=("status", "modified"))
    return created, True


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
        "free_until": _iso(event.free_until) if event.free_until else None,
        "is_follow": watch.target_booking_id is not None,
    }


def _iso(value: datetime) -> str:
    return value.astimezone(dt_timezone.utc).isoformat()


def record_events(*, watch: BenchSlotWatch, events: list[SlotEvent], now: datetime) -> int:
    created = 0
    for event in events:
        for channel in SlotWatchChannel.values:
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
                        "expires_at": min(event.free_until or now + NOTICE_LIFETIME, now + NOTICE_LIFETIME),
                    },
                )
            created += int(was_created)
    return created


def expire_finished_watches(*, now: datetime, limit: int = 500) -> int:
    ids = list(
        # Follows end with their booking (collect_follow), not with their range.
        BenchSlotWatch.objects.filter(status=SlotWatchStatus.ACTIVE, range_end__lte=now, target_booking__isnull=True)
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
            Q(target_booking__isnull=False)
            # Range watches: nothing can be "ending soon" further out than a day.
            | Q(range_end__gt=now, range_start__lt=now + timedelta(days=1)),
            user__is_active=True,
            pk__gt=after_watch_id,
            status=SlotWatchStatus.ACTIVE,
        )
        .select_related("user", "bench", "target_booking")
        .order_by("pk")[:PAGE_SIZE]
    )
    created = 0
    for watch in watches:
        if watch.target_booking_id is not None:
            rows, _ = collect_follow(watch=watch, now=now)
            created += rows
            continue
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
