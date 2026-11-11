"""check_agent_booking_login: may an agent log a user in with this booking code now?"""

from datetime import timedelta

import pytest
from django.utils import timezone

from core.labs.features.bench_bookings.public import (
    AgentBookingLogin,
    CheckAgentBookingLoginInput,
    check_agent_booking_login,
)
from core.labs.models import BenchBooking, BookingApprovalStatus, BookingStatus, EquipmentAssignment
from core.users.tests.factories import UserFactory
from tests.factories import ComputingEquipmentFactory


@pytest.fixture()
def computer(bench):
    equipment = ComputingEquipmentFactory()
    EquipmentAssignment.objects.create(
        equipment=equipment, bench=bench, assigned_at=timezone.now() - timedelta(days=1)
    )
    return equipment


@pytest.fixture()
def booking(make_booking, now):
    return make_booking(starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(hours=1), code="BK-LOGIN")


def check(computer, code="BK-LOGIN", *, now):
    return check_agent_booking_login(CheckAgentBookingLoginInput(equipment_id=computer.pk, booking_code=code), now=now)


@pytest.mark.django_db
def test_reserved_booking_on_this_bench_inside_its_window_is_eligible(computer, booking, actor, now):
    assert check(computer, now=now) == AgentBookingLogin(
        booking_code="BK-LOGIN",
        starts_at=booking.starts_at,
        ends_at=booking.ends_at,
        booked_for=actor.username,
    )


@pytest.mark.django_db
def test_booked_for_is_the_requester_when_set(computer, booking, now):
    requester = UserFactory(username="booked-for-someone")
    BenchBooking.objects.filter(pk=booking.pk).update(requester=requester)

    login = check(computer, now=now)

    assert login is not None and login.booked_for == "booked-for-someone"


@pytest.mark.django_db
def test_code_is_trimmed(computer, booking, now):
    assert check(computer, "  BK-LOGIN ", now=now) is not None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("start_offset", "eligible"),
    [
        (timedelta(minutes=1), False),  # before the start
        (timedelta(0), True),  # at the start
        (-timedelta(minutes=9, seconds=59), True),  # last second of the activation window
        (-timedelta(minutes=10), False),  # window closed: reconciliation expires it
    ],
)
def test_reserved_window_matches_activation_and_expiry(computer, make_booking, now, start_offset, eligible):
    make_booking(starts_at=now + start_offset, ends_at=now + timedelta(hours=1), code="BK-WINDOW")

    assert (check(computer, "BK-WINDOW", now=now) is not None) is eligible


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("end_offset", "eligible"),
    [(timedelta(seconds=1), True), (timedelta(0), False)],
)
def test_in_progress_booking_is_usable_until_it_ends(computer, make_booking, now, end_offset, eligible):
    make_booking(
        starts_at=now - timedelta(hours=2),
        ends_at=now + end_offset,
        status=BookingStatus.IN_PROGRESS,
        code="BK-RUNNING",
    )

    assert (check(computer, "BK-RUNNING", now=now) is not None) is eligible


@pytest.mark.django_db
@pytest.mark.parametrize("status", [BookingStatus.CANCELLED, BookingStatus.COMPLETED, BookingStatus.EXPIRED])
def test_finished_bookings_are_not_eligible(computer, make_booking, now, status):
    make_booking(starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(hours=1), status=status, code="BK-DONE")

    assert check(computer, "BK-DONE", now=now) is None


@pytest.mark.django_db
@pytest.mark.parametrize("approval", [BookingApprovalStatus.PENDING, BookingApprovalStatus.REJECTED])
def test_unapproved_bookings_are_not_eligible(computer, booking, now, approval):
    reason = "Rejected in test setup" if approval == BookingApprovalStatus.REJECTED else ""
    BenchBooking.objects.filter(pk=booking.pk).update(approval_status=approval, rejection_reason=reason)

    assert check(computer, now=now) is None


@pytest.mark.django_db
def test_booking_on_another_bench_is_not_eligible(computer, make_booking, other_bench, now):
    make_booking(
        starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(hours=1), bench_obj=other_bench, code="BK-OTHER"
    )

    assert check(computer, "BK-OTHER", now=now) is None


@pytest.mark.django_db
def test_computer_without_a_bench_is_not_eligible(booking, now):
    loose = ComputingEquipmentFactory()

    assert check(loose, now=now) is None


@pytest.mark.django_db
def test_computer_moved_off_the_bench_is_not_eligible(computer, booking, now):
    EquipmentAssignment.objects.filter(equipment=computer).update(unassigned_at=now - timedelta(minutes=1))

    assert check(computer, now=now) is None


@pytest.mark.django_db
@pytest.mark.parametrize("code", ["BK-UNKNOWN", "", "   "])
def test_unknown_or_blank_code_is_not_eligible(computer, booking, now, code):
    assert check(computer, code, now=now) is None


@pytest.mark.django_db
def test_two_queries_and_no_writes(computer, booking, now, django_assert_num_queries):
    before = BenchBooking.objects.values("status", "modified").get(pk=booking.pk)

    with django_assert_num_queries(2):
        assert check(computer, now=now) is not None

    assert BenchBooking.objects.values("status", "modified").get(pk=booking.pk) == before
