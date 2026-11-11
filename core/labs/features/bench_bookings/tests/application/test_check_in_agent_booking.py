"""check_in_agent_booking: the user enters a booking code at the agent and the booking starts."""

import uuid
from datetime import timedelta
from threading import Barrier, Thread

import pytest
from django.db import connection
from django.utils import timezone

from core.agents.models import AgentIdentity
from core.labs.features.bench_bookings.public import CheckInAgentBookingInput, check_in_agent_booking
from core.labs.models import BenchBooking, BookingApprovalStatus, BookingStatus, EquipmentAssignment
from tests.factories import create_computing_equipment


def make_agent(bench=None):
    equipment = create_computing_equipment(sku=f"CHECKIN-{uuid.uuid4().hex[:8]}", name="Check-in host")
    identity = AgentIdentity.objects.create(
        equipment=equipment,
        state=AgentIdentity.State.ACTIVE,
        public_key="test-public-key",
        public_key_sha256=uuid.uuid4().hex,
    )
    if bench is not None:
        EquipmentAssignment.objects.create(
            equipment=equipment, bench=bench, assigned_at=timezone.now() - timedelta(days=1)
        )
    return identity


@pytest.fixture()
def agent(bench):
    return make_agent(bench)


def check_in(agent, code="BK-CHECKIN", *, now):
    return check_in_agent_booking(
        CheckInAgentBookingInput(agent_uid=agent.agent_uid, booking_code=code), actor=None, now=now
    )


def status_of(booking):
    return BenchBooking.objects.values_list("status", flat=True).get(pk=booking.pk)


@pytest.mark.django_db
class TestCheckIn:
    def test_reserved_booking_becomes_in_progress(self, agent, make_booking, actor, now):
        booking = make_booking(
            starts_at=now - timedelta(minutes=2), ends_at=now + timedelta(hours=1), code="BK-CHECKIN"
        )

        result = check_in(agent, now=now)

        assert result is not None
        assert (result.booking_code, result.booked_for) == ("BK-CHECKIN", actor.username)
        assert status_of(booking) == BookingStatus.IN_PROGRESS

    def test_checking_in_again_succeeds_without_another_write(self, agent, make_booking, now):
        booking = make_booking(
            starts_at=now - timedelta(minutes=2), ends_at=now + timedelta(hours=1), code="BK-CHECKIN"
        )
        check_in(agent, now=now)
        modified = BenchBooking.objects.values_list("modified", flat=True).get(pk=booking.pk)

        again = check_in(agent, now=now + timedelta(minutes=30))  # e.g. the user logged out and back in

        assert again is not None
        assert status_of(booking) == BookingStatus.IN_PROGRESS
        assert BenchBooking.objects.values_list("modified", flat=True).get(pk=booking.pk) == modified

    @pytest.mark.parametrize(
        ("start_offset", "checked_in"),
        [
            (timedelta(minutes=1), False),  # before the start (O20)
            (timedelta(0), True),
            (-timedelta(minutes=9, seconds=59), True),
            (-timedelta(minutes=10), False),  # the reservation would already expire
        ],
    )
    def test_reserved_window(self, agent, make_booking, now, start_offset, checked_in):
        booking = make_booking(starts_at=now + start_offset, ends_at=now + timedelta(hours=1), code="BK-CHECKIN")

        assert (check_in(agent, now=now) is not None) is checked_in
        assert status_of(booking) == (BookingStatus.IN_PROGRESS if checked_in else BookingStatus.RESERVED)

    @pytest.mark.parametrize("approval", [BookingApprovalStatus.PENDING, BookingApprovalStatus.REJECTED])
    def test_unapproved_booking_is_not_checked_in(self, agent, make_booking, now, approval):
        booking = make_booking(
            starts_at=now - timedelta(minutes=2), ends_at=now + timedelta(hours=1), code="BK-CHECKIN"
        )
        reason = "Rejected in test setup" if approval == BookingApprovalStatus.REJECTED else ""
        BenchBooking.objects.filter(pk=booking.pk).update(approval_status=approval, rejection_reason=reason)

        assert check_in(agent, now=now) is None
        assert status_of(booking) == BookingStatus.RESERVED

    @pytest.mark.parametrize("status", [BookingStatus.CANCELLED, BookingStatus.COMPLETED, BookingStatus.EXPIRED])
    def test_finished_booking_is_not_checked_in(self, agent, make_booking, now, status):
        booking = make_booking(
            starts_at=now - timedelta(minutes=2), ends_at=now + timedelta(hours=1), status=status, code="BK-CHECKIN"
        )

        assert check_in(agent, now=now) is None
        assert status_of(booking) == status

    def test_booking_on_another_bench_is_not_checked_in(self, agent, make_booking, other_bench, now):
        booking = make_booking(
            starts_at=now - timedelta(minutes=2),
            ends_at=now + timedelta(hours=1),
            bench_obj=other_bench,
            code="BK-CHECKIN",
        )

        assert check_in(agent, now=now) is None
        assert status_of(booking) == BookingStatus.RESERVED

    def test_computer_without_a_bench_is_not_checked_in(self, make_booking, now):
        loose = make_agent()
        booking = make_booking(
            starts_at=now - timedelta(minutes=2), ends_at=now + timedelta(hours=1), code="BK-CHECKIN"
        )

        assert check_in(loose, now=now) is None
        assert status_of(booking) == BookingStatus.RESERVED

    def test_revoked_agent_is_not_checked_in(self, agent, make_booking, now):
        booking = make_booking(
            starts_at=now - timedelta(minutes=2), ends_at=now + timedelta(hours=1), code="BK-CHECKIN"
        )
        AgentIdentity.objects.filter(pk=agent.pk).update(state=AgentIdentity.State.REVOKED)

        assert check_in(agent, now=now) is None
        assert status_of(booking) == BookingStatus.RESERVED

    @pytest.mark.parametrize("code", ["BK-UNKNOWN", "", "   "])
    def test_unknown_or_blank_code(self, agent, make_booking, now, code):
        make_booking(starts_at=now - timedelta(minutes=2), ends_at=now + timedelta(hours=1), code="BK-CHECKIN")

        assert check_in(agent, code, now=now) is None


@pytest.mark.django_db(transaction=True)
def test_concurrent_check_ins_start_the_booking_once(bench, make_booking, now):
    """Two computers on the same bench check in with the same code at the same moment."""
    first, second = make_agent(bench), make_agent(bench)
    booking = make_booking(starts_at=now - timedelta(minutes=2), ends_at=now + timedelta(hours=1), code="BK-CHECKIN")
    barrier = Barrier(2)
    results, errors = [], []

    def run(agent):
        try:
            barrier.wait(timeout=5)
            results.append(check_in(agent, now=now))
        except Exception as error:  # surfaced by the assertion below
            errors.append(error)
        finally:
            connection.close()

    threads = [Thread(target=run, args=(agent,)) for agent in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert errors == []
    assert len(results) == 2 and all(result is not None for result in results)
    assert status_of(booking) == BookingStatus.IN_PROGRESS
