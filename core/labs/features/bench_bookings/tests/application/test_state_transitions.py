"""Integration tests for bench booking lifecycle transitions."""

from datetime import timedelta
from threading import Event, Thread

import pytest
from django.db import connection, transaction

from core.labs.features.bench_bookings.application import (
    UpdateBenchBookingInput,
    activate_bench_bookings,
    reconcile_bench_booking_statuses,
    update_bench_booking,
)
from core.labs.features.bench_bookings.exceptions import BenchBookingConflict
from core.labs.models import BenchBooking, BookingApprovalStatus, BookingStatus


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

    @pytest.mark.parametrize("approval", [BookingApprovalStatus.PENDING, BookingApprovalStatus.REJECTED])
    def test_unapproved_booking_is_not_activated(self, make_booking, now, approval):
        booking = make_booking(
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(hours=1),
            code="BOOKING-UNAPPROVED",
        )
        reason = "Rejected in test setup" if approval == BookingApprovalStatus.REJECTED else ""
        BenchBooking.objects.filter(pk=booking.pk).update(approval_status=approval, rejection_reason=reason)

        activated = activate_bench_bookings(bench_id=booking.bench_id, booking_code=booking.booking_code, now=now)

        booking.refresh_from_db()
        assert activated == 0
        assert booking.status == BookingStatus.RESERVED

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


@pytest.mark.django_db
class TestBatchedReconciliation:
    def _overdue_reserved(self, make_booking, now, count):
        return [
            make_booking(
                starts_at=now - timedelta(hours=10 - index, minutes=30),
                ends_at=now - timedelta(hours=10 - index),
            )
            for index in range(count)
        ]

    def test_backlog_larger_than_one_batch_is_drained(self, make_booking, now):
        bookings = self._overdue_reserved(make_booking, now, 5)

        result = reconcile_bench_booking_statuses(now=now, batch_size=2)

        assert result == {"expired": 5, "completed": 0}
        assert set(BenchBooking.objects.filter(pk__in=[b.pk for b in bookings]).values_list("status", flat=True)) == {
            BookingStatus.EXPIRED
        }

    def test_query_count_does_not_grow_per_row(self, make_booking, now, django_assert_max_num_queries):
        self._overdue_reserved(make_booking, now, 6)

        # Per move: savepoint + select ids + update + release, plus one empty probe per move.
        with django_assert_max_num_queries(12):
            reconcile_bench_booking_statuses(now=now)

    def test_rerun_is_a_no_op(self, make_booking, now):
        self._overdue_reserved(make_booking, now, 2)
        reconcile_bench_booking_statuses(now=now)

        assert reconcile_bench_booking_statuses(now=now) == {"expired": 0, "completed": 0}


@pytest.mark.django_db(transaction=True)
def test_reconciliation_skips_rows_locked_by_a_concurrent_command(make_booking, now):
    locked, free = (
        make_booking(starts_at=now - timedelta(hours=2), ends_at=now - timedelta(hours=1)),
        make_booking(starts_at=now - timedelta(hours=4), ends_at=now - timedelta(hours=3)),
    )
    acquired, release = Event(), Event()

    def hold_lock():
        try:
            with transaction.atomic():
                BenchBooking.objects.select_for_update().get(pk=locked.pk)
                acquired.set()
                release.wait(timeout=10)
        finally:
            connection.close()

    holder = Thread(target=hold_lock)
    holder.start()
    try:
        assert acquired.wait(timeout=10)
        result = reconcile_bench_booking_statuses(now=now)  # must not block on the held row
    finally:
        release.set()
        holder.join(timeout=10)

    assert result == {"expired": 1, "completed": 0}
    assert BenchBooking.objects.get(pk=free.pk).status == BookingStatus.EXPIRED
    assert BenchBooking.objects.get(pk=locked.pk).status == BookingStatus.RESERVED
    assert reconcile_bench_booking_statuses(now=now) == {"expired": 1, "completed": 0}
