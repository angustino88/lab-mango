"""Create and cancel bench slot watches.

Race guards:
* create: the partial unique constraint ``slot_watch_active_unique`` makes a repeated request
  return the existing active watch; the per-user cap is checked under a lock on the user's row.
* cancel: row lock on the watch; cancelling an already cancelled or expired watch is a no-op.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.common.domain.errors import ValidationFailed
from core.labs.models import Bench, BenchSlotWatch, SlotWatchStatus

from ..exceptions import BenchBookingPermissionDenied

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
        # Serializes this user's creates so the cap cannot be raced past.
        get_user_model().objects.select_for_update().filter(pk=actor.pk).first()
        existing = BenchSlotWatch.objects.filter(status=SlotWatchStatus.ACTIVE, **lookup).first()
        if existing is not None:
            return existing
        active = BenchSlotWatch.objects.filter(
            user_id=actor.pk, status=SlotWatchStatus.ACTIVE, range_end__gt=now
        ).count()
        if active >= MAX_ACTIVE_WATCHES_PER_USER:
            raise SlotWatchInvalid(
                f"You can watch at most {MAX_ACTIVE_WATCHES_PER_USER} ranges at once.",
                code="slot_watch_limit",
            )
        try:
            with transaction.atomic():
                return BenchSlotWatch.objects.create(**lookup)
        except IntegrityError:
            # Defensive: the user lock already serializes this path.
            return BenchSlotWatch.objects.get(status=SlotWatchStatus.ACTIVE, **lookup)


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
]
