"""Create and cancel bench slot watches.

Race guards:
* create: the partial unique constraint ``slot_watch_active_unique`` makes a repeated request
  return the existing active watch; the per-user cap is checked under a lock on the user's row.
* follow: same user lock and cap; the partial unique constraint ``slot_watch_follow_unique`` makes a repeated
  follow of the same booking return the existing one.
* cancel: row lock on the watch; cancelling an already cancelled or expired watch is a no-op.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.common.domain.errors import ValidationFailed
from core.labs.models import Bench, BenchBooking, BenchSlotWatch, Booking, SlotWatchStatus

from ..exceptions import BenchBookingPermissionDenied
from ..queries.bench_bookings import visible_to

MAX_ACTIVE_WATCHES_PER_USER = 20
MAX_RANGE = timedelta(days=7)
MAX_LOOKAHEAD = timedelta(days=60)


class SlotWatchInvalid(ValidationFailed):
    code = "slot_watch_invalid"


@dataclass(frozen=True, slots=True)
class CreateSlotWatchInput:
    bench_id: int
    range_start: datetime
    range_end: datetime


def _require_user(actor) -> None:
    if actor is None or not getattr(actor, "is_authenticated", False) or not getattr(actor, "pk", None):
        raise BenchBookingPermissionDenied("Slot watches belong to a signed-in user.")


def _validate(data: CreateSlotWatchInput, *, now: datetime) -> None:
    errors: dict[str, str] = {}
    if data.range_end <= data.range_start:
        errors["range_end"] = "Must be after range_start."
    elif data.range_end - data.range_start > MAX_RANGE:
        errors["range_end"] = "A watched range can span at most 7 days."
    elif data.range_end <= now:
        errors["range_end"] = "Must be in the future."
    if data.range_start > now + MAX_LOOKAHEAD:
        errors["range_start"] = "Must be within the next 60 days."
    if errors:
        raise SlotWatchInvalid("The slot watch is not valid.", details=errors)


def create_slot_watch(*, actor, data: CreateSlotWatchInput, now: datetime | None = None) -> BenchSlotWatch:
    """Start watching a bench range. Idempotent for the same user, bench and range."""
    _require_user(actor)
    now = now or timezone.now()
    _validate(data, now=now)
    bench = Bench.objects.get(pk=data.bench_id)  # DoesNotExist -> 404

    lookup = {"user_id": actor.pk, "bench": bench, "range_start": data.range_start, "range_end": data.range_end}
    with transaction.atomic():
        _lock_user(actor)
        existing = BenchSlotWatch.objects.filter(
            status=SlotWatchStatus.ACTIVE, target_booking__isnull=True, **lookup
        ).first()
        if existing is not None:
            return existing
        _ensure_below_cap(actor)
        try:
            with transaction.atomic():
                return BenchSlotWatch.objects.create(**lookup)
        except IntegrityError:
            # Defensive: the user lock already serializes this path.
            return BenchSlotWatch.objects.get(status=SlotWatchStatus.ACTIVE, target_booking__isnull=True, **lookup)


def _lock_user(actor) -> None:
    """Serializes one user's creates and follows so the cap cannot be raced past."""
    get_user_model().objects.select_for_update().filter(pk=actor.pk).first()


def _ensure_below_cap(actor) -> None:
    if BenchSlotWatch.objects.filter(user_id=actor.pk, status=SlotWatchStatus.ACTIVE).count() >= (
        MAX_ACTIVE_WATCHES_PER_USER
    ):
        raise SlotWatchInvalid(
            f"You can have at most {MAX_ACTIVE_WATCHES_PER_USER} active slot alerts.",
            code="slot_watch_limit",
        )


def follow_booking(*, actor, booking_id: int, now: datetime | None = None) -> BenchSlotWatch:
    """One alert when this booking is about to end, completes, or is cancelled/expired/rejected.

    Visible scope: any booking on the shared calendar (still reserving), or one the actor may read.
    Anything else is 404, so ids cannot be probed. Idempotent per user and booking.
    """
    _require_user(actor)
    now = now or timezone.now()
    calendar = BenchBooking.objects.filter(
        status__in=Booking.ACTIVE_STATUSES, approval_status__in=Booking.RESERVING_APPROVAL_STATUSES
    )
    booking = (calendar | visible_to(BenchBooking.objects.all(), actor=actor)).get(pk=booking_id)  # else 404
    if booking.creator_id == actor.pk:
        raise SlotWatchInvalid("This is your own booking.", code="slot_watch_own_booking")
    if not (
        booking.status in Booking.ACTIVE_STATUSES
        and booking.approval_status in Booking.RESERVING_APPROVAL_STATUSES
        and booking.ends_at > now
    ):
        raise SlotWatchInvalid(
            "This booking has already ended, so the bench is free to book.", code="slot_watch_ended"
        )
    with transaction.atomic():
        _lock_user(actor)
        existing = BenchSlotWatch.objects.filter(
            user_id=actor.pk, target_booking=booking, status=SlotWatchStatus.ACTIVE
        ).first()
        if existing is not None:
            return existing
        _ensure_below_cap(actor)
        try:
            with transaction.atomic():
                return BenchSlotWatch.objects.create(
                    user_id=actor.pk,
                    bench_id=booking.bench_id,
                    target_booking=booking,
                    range_start=min(now, booking.ends_at - timedelta(seconds=1)),
                    range_end=booking.ends_at,
                )
        except IntegrityError:
            return BenchSlotWatch.objects.get(user_id=actor.pk, target_booking=booking, status=SlotWatchStatus.ACTIVE)


def cancel_slot_watch(*, actor, watch_id: int) -> BenchSlotWatch:
    """Stop a watch. Only its owner may; others get 404 (no existence oracle). Safe to repeat."""
    _require_user(actor)
    with transaction.atomic():
        watch = BenchSlotWatch.objects.select_for_update().get(pk=watch_id, user_id=actor.pk)
        if watch.status == SlotWatchStatus.ACTIVE:
            watch.status = SlotWatchStatus.CANCELLED
            watch.save(update_fields=("status", "modified"))
    return watch


__all__ = [
    "MAX_ACTIVE_WATCHES_PER_USER",
    "CreateSlotWatchInput",
    "SlotWatchInvalid",
    "cancel_slot_watch",
    "create_slot_watch",
    "follow_booking",
]
