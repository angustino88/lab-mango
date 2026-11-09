"""Integration tests for bench booking lifecycle transitions."""

from datetime import timedelta

import pytest

from core.labs.features.bench_bookings.application import (
    UpdateBenchBookingInput,
    activate_bench_bookings,
    reconcile_bench_booking_statuses,
    update_bench_booking,
)
from core.labs.features.bench_bookings.exceptions import BenchBookingConflict
from core.labs.models import BookingStatus


@pytest.mark.django_db
class TestActivation:
    def test_active_computing_booking_moves_reserved_booking_to_in_progress(self, make_booking, now):
        booking = make_booking(
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(hours=1),
            code="BOOKING-ACTIVE",
        )

        activated = activate_bench_bookings(
            bench_id=booking.bench_id,
            booking_code=booking.booking_code,
            now=now,
        )

        booking.refresh_from_db()
        assert activated == 1
        assert booking.status == BookingStatus.IN_PROGRESS

    def test_active_computing_does_not_activate_outside_booking_window(self, make_booking, now):
        booking = make_booking(
            starts_at=now + timedelta(minutes=1),
            ends_at=now + timedelta(hours=1),
            code="BOOKING-FUTURE",
        )

        activated = activate_bench_bookings(
            bench_id=booking.bench_id,
            booking_code=booking.booking_code,
            now=now,
        )

        booking.refresh_from_db()
        assert activated == 0
        assert booking.status == BookingStatus.RESERVED


@pytest.mark.django_db
class TestReconciliation:
    def test_reserved_booking_expires_ten_minutes_after_start(self, make_booking, now):
        booking = make_booking(
            starts_at=now - timedelta(minutes=10),
            ends_at=now + timedelta(hours=1),
        )

        result = reconcile_bench_booking_statuses(now=now)

        booking.refresh_from_db()
        assert result == {"expired": 1, "completed": 0}
        assert booking.status == BookingStatus.EXPIRED

    def test_reserved_booking_is_not_expired_before_ten_minutes(self, make_booking, now):
        booking = make_booking(
            starts_at=now - timedelta(minutes=9, seconds=59),
            ends_at=now + timedelta(hours=1),
        )

        reconcile_bench_booking_statuses(now=now)

        booking.refresh_from_db()
        assert booking.status == BookingStatus.RESERVED

    def test_in_progress_booking_completes_at_end_time(self, make_booking, now):
        booking = make_booking(
            starts_at=now - timedelta(hours=1),
            ends_at=now,
            status=BookingStatus.IN_PROGRESS,
        )

        result = reconcile_bench_booking_statuses(now=now)

        booking.refresh_from_db()
        assert result == {"expired": 0, "completed": 1}
        assert booking.status == BookingStatus.COMPLETED

    def test_in_progress_booking_does_not_complete_before_end_time(self, make_booking, now):
        booking = make_booking(
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(microseconds=1),
            status=BookingStatus.IN_PROGRESS,
        )

        reconcile_bench_booking_statuses(now=now)

        booking.refresh_from_db()
        assert booking.status == BookingStatus.IN_PROGRESS


@pytest.mark.django_db
class TestExpiredBookingUpdates:
    def test_rejects_update_after_reserved_booking_activation_window(self, actor, make_booking, now):
        booking = make_booking(
            starts_at=now - timedelta(minutes=11),
            ends_at=now + timedelta(hours=1),
        )

        with pytest.raises(BenchBookingConflict, match="booking has expired"):
            update_bench_booking(
                actor=actor,
                data=UpdateBenchBookingInput(booking_id=booking.pk, fields={"reason": "Changed"}),
            )

        booking.refresh_from_db()
        assert booking.reason == ""

    def test_allows_update_before_reserved_booking_activation_window_ends(self, actor, make_booking, now):
        booking = make_booking(
            starts_at=now - timedelta(minutes=9),
            ends_at=now + timedelta(hours=1),
        )

        updated = update_bench_booking(
            actor=actor,
            data=UpdateBenchBookingInput(booking_id=booking.pk, fields={"reason": "Changed"}),
        )

        assert updated.reason == "Changed"

    def test_allows_cancellation_after_reserved_booking_activation_window(self, actor, make_booking, now):
        booking = make_booking(
            starts_at=now - timedelta(minutes=11),
            ends_at=now + timedelta(hours=1),
        )

        updated = update_bench_booking(
            actor=actor,
            data=UpdateBenchBookingInput(booking_id=booking.pk, fields={"status": BookingStatus.CANCELLED}),
        )

        assert updated.status == BookingStatus.CANCELLED
