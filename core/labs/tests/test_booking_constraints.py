"""PostgreSQL guards for booking approval and cancellation invariants (migration 0015).

Each rule mirrors Booking.clean(); the database must reject a violating write even when
it bypasses clean() (queryset.update, admin, raw ORM saves).
"""

from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from core.labs.models import BenchBooking, BookingApprovalStatus, BookingStatus
from tests.factories import BenchFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def booking():
    starts_at = timezone.now() + timedelta(days=1)
    return BenchBooking.objects.create(
        bench=BenchFactory(),
        booking_code="BOOKING-CONSTRAINT-01",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
    )


def _rejects(booking, constraint, **values):
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        BenchBooking.objects.filter(pk=booking.pk).update(**values)


@pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
def test_rejected_booking_requires_nonblank_reason(booking, reason):
    approver = UserFactory(username="constraint-approver")
    _rejects(
        booking,
        "labs_benchbooking_rejection_has_reason",
        approval_status=BookingApprovalStatus.REJECTED,
        approved_by=approver,
        rejection_reason=reason,
    )


def test_pending_booking_cannot_keep_an_approver(booking):
    _rejects(
        booking,
        "labs_benchbooking_pending_has_no_approver",
        approval_status=BookingApprovalStatus.PENDING,
        approved_by=UserFactory(username="constraint-stale-approver"),
    )


@pytest.mark.parametrize("reason", ["", "  "])
def test_cancelled_booking_requires_nonblank_reason(booking, reason):
    _rejects(
        booking,
        "labs_benchbooking_cancellation_has_reason",
        status=BookingStatus.CANCELLED,
        cancellation_reason=reason,
    )


def test_valid_states_are_accepted(booking):
    approver = UserFactory(username="constraint-valid-approver")
    BenchBooking.objects.filter(pk=booking.pk).update(
        approval_status=BookingApprovalStatus.REJECTED, approved_by=approver, rejection_reason="Lab closed"
    )
    BenchBooking.objects.filter(pk=booking.pk).update(
        status=BookingStatus.CANCELLED, cancellation_reason="No longer needed"
    )
    # Rejected bookings may lose their approver when that user is deleted (approved_by is SET_NULL).
    BenchBooking.objects.filter(pk=booking.pk).update(approved_by=None)


def test_constraints_are_not_validated_against_history():
    """Added NOT VALID so deploys never fail or scan on historical rows."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT conname, convalidated FROM pg_constraint "
            "WHERE conname LIKE 'labs_%%booking_%%has_reason' OR conname LIKE 'labs_%%booking_pending_has_no_approver'"
        )
        rows = dict(cursor.fetchall())
    assert set(rows) == {
        f"labs_{model}_{rule}"
        for model in ("benchbooking", "equipmentbooking")
        for rule in ("rejection_has_reason", "pending_has_no_approver", "cancellation_has_reason")
    }
    assert not any(rows.values())
