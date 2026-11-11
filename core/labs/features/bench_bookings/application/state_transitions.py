"""Explicit state transitions for bench bookings."""

from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.labs.models import BenchBooking, BookingStatus, ComputingActivityStatus, EquipmentAssignment
from core.labs.models.booking import ensure_booking_status_transition

from .policies import ACTIVATION_WINDOW


def activate_bench_bookings(*, bench_id: int, booking_code: str, now: datetime) -> int:
    """Move one matching reserved booking to in progress after confirmed activity."""
    with transaction.atomic():
        booking = (
            BenchBooking.objects.select_for_update()
            .filter(
                bench_id=bench_id,
                booking_code=booking_code,
                status=BookingStatus.RESERVED,
                starts_at__lte=now,
                ends_at__gt=now,
            )
            .first()
        )
        if booking is None:
            return 0
        _transition(booking, BookingStatus.IN_PROGRESS)
    return 1


def activate_bench_booking_for_computing_activity(*, computing_id: int, now: datetime) -> int:
    """Activate a booking when its assigned computing resource reports active use."""
    assignment = (
        EquipmentAssignment.objects.select_related("equipment__activity")
        .filter(equipment_id=computing_id, unassigned_at__isnull=True)
        .order_by("pk")
        .first()
    )
    if assignment is None:
        return 0

    activity = getattr(assignment.equipment, "activity", None)
    if activity is None or activity.status != ComputingActivityStatus.ACTIVE or not activity.booking_code:
        return 0

    return activate_bench_bookings(
        bench_id=assignment.bench_id,
        booking_code=activity.booking_code,
        now=now,
    )


RECONCILE_BATCH_SIZE = 500

# Each reconciliation move is a valid edge of BOOKING_STATUS_TRANSITIONS; the
# filters below select only rows whose current status is the source state.
_RECONCILE_MOVES = (
    ("expired", BookingStatus.RESERVED, BookingStatus.EXPIRED),
    ("completed", BookingStatus.IN_PROGRESS, BookingStatus.COMPLETED),
)


def reconcile_bench_booking_statuses(*, now: datetime, batch_size: int = RECONCILE_BATCH_SIZE) -> dict[str, int]:
    """Expire unattended reservations and complete finished active bookings.

    Race guard: each batch locks its rows with ``SKIP LOCKED`` and re-checks the
    source status in the UPDATE, so rows held by a concurrent user command are
    left for the next run instead of blocking it. Each batch commits on its own,
    keeping lock time bounded however large the backlog. Safe to run repeatedly.
    """
    for _, source, target in _RECONCILE_MOVES:
        ensure_booking_status_transition(current_status=source, target_status=target)
    due = {
        "expired": Q(status=BookingStatus.RESERVED, starts_at__lte=now - ACTIVATION_WINDOW),
        "completed": Q(status=BookingStatus.IN_PROGRESS, ends_at__lte=now),
    }
    result = {}
    for key, source, target in _RECONCILE_MOVES:
        result[key] = _transition_in_batches(due[key], source=source, target=target, batch_size=batch_size)
    return result


def _transition_in_batches(condition: Q, *, source: BookingStatus, target: BookingStatus, batch_size: int) -> int:
    total = 0
    while True:
        with transaction.atomic():
            ids = list(
                BenchBooking.objects.select_for_update(skip_locked=True)
                .filter(condition)
                .order_by("pk")
                .values_list("pk", flat=True)[:batch_size]
            )
            if not ids:
                return total
            total += BenchBooking.objects.filter(pk__in=ids, status=source).update(
                status=target, modified=timezone.now()
            )
        if len(ids) < batch_size:
            return total


def _transition(booking: BenchBooking, target_status: BookingStatus) -> None:
    ensure_booking_status_transition(current_status=booking.status, target_status=target_status)
    booking.status = target_status
    booking.save(update_fields=("status", "modified"))
