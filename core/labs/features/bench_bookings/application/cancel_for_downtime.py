"""Cancel bench bookings that overlap a downtime window (called by the downtime feature, RS4)."""

from dataclasses import dataclass

from django.db import transaction

from core.labs.models import BenchBooking, BookingStatus, ensure_booking_status_transition

from .locks import lock_benches
from .notification_intents import record_notification


@dataclass(frozen=True, slots=True)
class CancelBookingsForDowntimeInput:
    booking_ids: tuple[int, ...]
    reason: str


def cancel_bench_bookings_for_downtime(*, actor, data: CancelBookingsForDowntimeInput) -> list[int]:
    """Cancel the listed reserved or in-progress bookings with ``reason``; return the cancelled IDs.

    Race guard: the bench rows (``lock_benches``, the bench booking lock), then the booking rows in
    PK order. Idempotent: a booking already cancelled, completed or expired is skipped.
    """
    with transaction.atomic():
        bench_ids = BenchBooking.objects.filter(pk__in=data.booking_ids).values_list("bench_id", flat=True)
        lock_benches(set(bench_ids))
        bookings = list(
            BenchBooking.objects.select_for_update()
            .filter(pk__in=data.booking_ids, status__in=(BookingStatus.RESERVED, BookingStatus.IN_PROGRESS))
            .order_by("pk")
        )
        for booking in bookings:
            ensure_booking_status_transition(current_status=booking.status, target_status=BookingStatus.CANCELLED)
            booking.status = BookingStatus.CANCELLED
            booking.cancellation_reason = data.reason
            booking.save(actor=actor, update_fields=("status", "cancellation_reason", "modified"))
            record_notification(booking=booking, kind="updated")
    return [booking.pk for booking in bookings]


__all__ = ["CancelBookingsForDowntimeInput", "cancel_bench_bookings_for_downtime"]
