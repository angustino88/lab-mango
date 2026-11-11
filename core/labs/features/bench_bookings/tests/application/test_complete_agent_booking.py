"""complete_agent_booking: the user chooses to end the booking at the agent."""

import uuid
from datetime import timedelta
from threading import Barrier, Thread

import pytest
from django.db import connection
from django.utils import timezone

from core.agents.models import AgentIdentity
from core.labs.features.bench_bookings.public import (
    CheckInAgentBookingInput,
    CompleteAgentBookingInput,
    check_in_agent_booking,
    complete_agent_booking,
)
from core.labs.models import BenchBooking, BookingApprovalStatus, BookingStatus, EquipmentAssignment
from tests.factories import create_computing_equipment


def make_agent(bench=None):
    equipment = create_computing_equipment(sku=f"END-{uuid.uuid4().hex[:8]}", name="End host")
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


@pytest.fixture()
def running(make_booking, now):
    return make_booking(
        starts_at=now - timedelta(minutes=30),
        ends_at=now + timedelta(hours=1),
        status=BookingStatus.IN_PROGRESS,
        code="BK-END",
    )


def end(agent, code="BK-END"):
    return complete_agent_booking(CompleteAgentBookingInput(agent_uid=agent.agent_uid, booking_code=code), actor=None)


def status_of(booking):
    return BenchBooking.objects.values_list("status", flat=True).get(pk=booking.pk)


@pytest.mark.django_db
class TestEndBooking:
    def test_in_progress_booking_becomes_completed(self, agent, running):
        result = end(agent)

        assert result is not None
        assert (result.booking_code, result.starts_at, result.ends_at) == (
            "BK-END",
            running.starts_at,
            running.ends_at,
        )
        assert status_of(running) == BookingStatus.COMPLETED

    def test_booked_end_time_is_kept(self, agent, running):
        end(agent)

        assert BenchBooking.objects.values_list("ends_at", flat=True).get(pk=running.pk) == running.ends_at

    def test_ending_again_succeeds_without_another_write(self, agent, running):
        end(agent)
        modified = BenchBooking.objects.values_list("modified", flat=True).get(pk=running.pk)

        assert end(agent) is not None
        assert BenchBooking.objects.values_list("modified", flat=True).get(pk=running.pk) == modified

    def test_checked_in_booking_can_be_ended(self, agent, make_booking, now):
        booking = make_booking(starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(hours=1), code="BK-END")
        check_in_agent_booking(CheckInAgentBookingInput(agent_uid=agent.agent_uid, booking_code="BK-END"), actor=None)

        assert end(agent) is not None
        assert status_of(booking) == BookingStatus.COMPLETED

    def test_ended_booking_cannot_be_checked_in_again(self, agent, running, now):
        end(agent)

        again = check_in_agent_booking(
            CheckInAgentBookingInput(agent_uid=agent.agent_uid, booking_code="BK-END"), actor=None, now=now
        )

        assert again is None
        assert status_of(running) == BookingStatus.COMPLETED

    def test_ending_frees_the_bench_for_a_new_booking(self, agent, running, make_booking, now):
        from core.labs.features.bench_bookings.queries import conflicting_bench_bookings

        end(agent)

        assert not conflicting_bench_bookings(
            bench_id=running.bench_id, starts_at=now + timedelta(minutes=5), ends_at=now + timedelta(minutes=50)
        ).exists()

    @pytest.mark.parametrize("status", [BookingStatus.RESERVED, BookingStatus.CANCELLED, BookingStatus.EXPIRED])
    def test_booking_that_is_not_running_cannot_be_ended(self, agent, make_booking, now, status):
        booking = make_booking(
            starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(hours=1), status=status, code="BK-END"
        )

        assert end(agent) is None
        assert status_of(booking) == status

    @pytest.mark.parametrize("approval", [BookingApprovalStatus.PENDING, BookingApprovalStatus.REJECTED])
    def test_unapproved_booking_cannot_be_ended(self, agent, running, approval):
        reason = "Rejected in test setup" if approval == BookingApprovalStatus.REJECTED else ""
        BenchBooking.objects.filter(pk=running.pk).update(approval_status=approval, rejection_reason=reason)

        assert end(agent) is None
        assert status_of(running) == BookingStatus.IN_PROGRESS

    def test_agent_on_another_bench_cannot_end_it(self, running, other_bench):
        elsewhere = make_agent(other_bench)

        assert end(elsewhere) is None
        assert status_of(running) == BookingStatus.IN_PROGRESS

    def test_revoked_agent_cannot_end_it(self, agent, running):
        AgentIdentity.objects.filter(pk=agent.pk).update(state=AgentIdentity.State.REVOKED)

        assert end(agent) is None
        assert status_of(running) == BookingStatus.IN_PROGRESS

    @pytest.mark.parametrize("code", ["BK-UNKNOWN", "", "   "])
    def test_unknown_or_blank_code(self, agent, running, code):
        assert end(agent, code) is None
        assert status_of(running) == BookingStatus.IN_PROGRESS


@pytest.mark.django_db(transaction=True)
def test_concurrent_ends_complete_the_booking_once(bench, make_booking, now):
    first, second = make_agent(bench), make_agent(bench)
    booking = make_booking(
        starts_at=now - timedelta(minutes=30),
        ends_at=now + timedelta(hours=1),
        status=BookingStatus.IN_PROGRESS,
        code="BK-END",
    )
    barrier = Barrier(2)
    results, errors = [], []

    def run(agent):
        try:
            barrier.wait(timeout=5)
            results.append(end(agent))
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
    assert status_of(booking) == BookingStatus.COMPLETED
