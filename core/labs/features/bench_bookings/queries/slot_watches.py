"""Slot watch selectors; a user only ever sees their own watches."""

from datetime import datetime, timedelta

from django.db.models import QuerySet
from django.utils import timezone

from core.labs.models import BenchBooking, BenchSlotWatch, Booking, SlotWatchStatus

from ..contracts import free_intervals


def list_slot_watches(
    *, actor, status: str | None = None, updated_after: datetime | None = None
) -> QuerySet[BenchSlotWatch]:
    user_id = getattr(actor, "pk", None) if getattr(actor, "is_authenticated", False) else None
    if user_id is None:
        return BenchSlotWatch.objects.none()
    queryset = BenchSlotWatch.objects.filter(user_id=user_id).select_related("bench")
    if status:
        queryset = queryset.filter(status=status)
    if updated_after is not None:
        queryset = queryset.filter(modified__gte=updated_after)
    return queryset.order_by("range_start", "pk")


def get_slot_watch(*, actor, watch_id: int) -> BenchSlotWatch:
    """The actor's watch, or ``DoesNotExist`` (404) for anyone else's."""
    return list_slot_watches(actor=actor).get(pk=watch_id)


# --- Availability shown with each active alert (the "queue view" of a bench) ------------------

FOLLOW_TAIL = timedelta(hours=2)
MAX_BUSY_PERIODS = 20


def slot_availability(watch: BenchSlotWatch, *, now: datetime | None = None) -> dict | None:
    """Busy periods, next free time and demand for a watch's bench, inside the watched window.

    Busy periods are anonymous (only ``is_mine`` for the viewer's own bookings). ``watcher_count`` counts
    other users with an active alert on the same bench overlapping the window, never who they are.
    Two bounded queries per watch; a user has at most 20 active watches.
    """
    if watch.status != SlotWatchStatus.ACTIVE:
        return None
    now = now or timezone.now()
    lo = max(watch.range_start, now)
    hi = watch.range_end + FOLLOW_TAIL if watch.target_booking_id else watch.range_end
    if lo >= hi:
        return None
    bookings = list(
        BenchBooking.objects.filter(
            bench_id=watch.bench_id,
            starts_at__lt=hi,
            ends_at__gt=lo,
            status__in=Booking.ACTIVE_STATUSES,
            approval_status__in=Booking.RESERVING_APPROVAL_STATUSES,
        )
        .order_by("starts_at", "pk")
        .only("starts_at", "ends_at", "creator_id")[:MAX_BUSY_PERIODS]
    )
    busy = [(max(b.starts_at, lo), min(b.ends_at, hi)) for b in bookings]
    gaps = free_intervals((lo, hi), busy)
    watcher_count = (
        BenchSlotWatch.objects.filter(
            bench_id=watch.bench_id,
            status=SlotWatchStatus.ACTIVE,
            range_start__lt=hi,
            range_end__gt=lo,
        )
        .exclude(user_id=watch.user_id)
        .values("user_id")
        .distinct()
        .count()
    )
    return {
        "window_starts_at": lo,
        "window_ends_at": hi,
        "busy_periods": [
            {"starts_at": start, "ends_at": end, "is_mine": b.creator_id == watch.user_id}
            for (start, end), b in zip(busy, bookings, strict=True)
        ],
        "next_free_starts_at": gaps[0][0] if gaps else None,
        "next_free_ends_at": gaps[0][1] if gaps else None,
        "watcher_count": watcher_count,
    }
