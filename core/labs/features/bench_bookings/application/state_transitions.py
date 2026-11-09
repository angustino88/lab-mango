"""Explicit state transitions for bench bookings."""

from datetime import datetime

from django.db import transaction

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
        EquipmentAssignment.objects.select_related("equipment__computingequipment__activity")
        .filter(equipment_id=computing_id, unassigned_at__isnull=True)
        .order_by("pk")
        .first()
    )
    if assignment is None:
        return 0

    activity = assignment.equipment.computingequipment.activity
    if activity.status != ComputingActivityStatus.ACTIVE or not activity.booking_code:
        return 0

    return activate_bench_bookings(
        bench_id=assignment.bench_id,
        booking_code=activity.booking_code,
        now=now,
    )


def reconcile_bench_booking_statuses(*, now: datetime) -> dict[str, int]:
    """Expire unattended reservations and complete finished active bookings."""
    with transaction.atomic():
        expired = _transition_all(
            BenchBooking.objects.select_for_update().filter(
                status=BookingStatus.RESERVED,
                starts_at__lte=now - ACTIVATION_WINDOW,
            ),
            BookingStatus.EXPIRED,
        )
        completed = _transition_all(
            BenchBooking.objects.select_for_update().filter(
                status=BookingStatus.IN_PROGRESS,
                ends_at__lte=now,
            ),
            BookingStatus.COMPLETED,
        )
    return {"expired": expired, "completed": completed}


def _transition(booking: BenchBooking, target_status: BookingStatus) -> None:
    ensure_booking_status_transition(current_status=booking.status, target_status=target_status)
    booking.status = target_status
    booking.save(update_fields=("status", "modified"))


def _transition_all(bookings, target_status: BookingStatus) -> int:
    count = 0
    for booking in bookings:
        _transition(booking, target_status)
        count += 1
    return count
