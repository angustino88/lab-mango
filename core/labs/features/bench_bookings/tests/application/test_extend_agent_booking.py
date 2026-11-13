"""extend_agent_booking: the user asks for more time at the agent (rules E1–E8, decision O28)."""

import importlib
import uuid
from datetime import timedelta
from threading import Barrier, Thread

import pytest
from django.db import connection
from django.utils import timezone

from core.agents.models import AgentIdentity
from core.labs.features.bench_bookings.public import (
    AgentExtensionBenchNotFree,
    AgentExtensionNotAllowed,
    BenchBookingConflict,
    CheckInAgentBookingInput,
    CreateBenchBookingInput,
    ExtendAgentBookingInput,
    check_in_agent_booking,
    create_bench_booking,
    extend_agent_booking,
)
from core.labs.models import Bench, BenchBooking, BookingApprovalStatus, BookingStatus, EquipmentAssignment
from tests.factories import create_computing_equipment

extend_module = importlib.import_module("core.labs.features.bench_bookings.application.extend_agent_booking")


def make_agent(bench=None):
    equipment = create_computing_equipment(sku=f"EXT-{uuid.uuid4().hex[:8]}", name="Extend host")
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
def start():
    return timezone.now().replace(second=0, microsecond=0) - timedelta(minutes=30)


@pytest.fixture()
def agent(bench):
    return make_agent(bench)


@pytest.fixture()
def running(make_booking, start):
    """Started 30 minutes ago, booked for 90 minutes."""
    return make_booking(
        starts_at=start, ends_at=start + timedelta(minutes=90), status=BookingStatus.IN_PROGRESS, code="BK-EXT"
    )


def extend(agent, ends_at, code="BK-EXT", now=None):
    return extend_agent_booking(
        ExtendAgentBookingInput(agent_uid=agent.agent_uid, booking_code=code, ends_at=ends_at), actor=None, now=now
    )


def ends_at_of(booking):
    return BenchBooking.objects.values_list("ends_at", flat=True).get(pk=booking.pk)


def refusal(error) -> tuple:
    return error.value.details["reason"], error.value.details["limit"]


@pytest.mark.django_db
class TestExtend:
    def test_extends_the_running_booking(self, agent, running, start, monkeypatch):
        notified = []
        monkeypatch.setattr(extend_module, "record_notification", lambda **kwargs: notified.append(kwargs))

        result = extend(agent, start + timedelta(hours=2))

        assert result is not None and result.ends_at == start + timedelta(hours=2)
        assert ends_at_of(running) == start + timedelta(hours=2)
        assert [(n["booking"].pk, n["kind"]) for n in notified] == [(running.pk, "updated")]  # E8

    def test_seconds_are_dropped(self, agent, running, start):
        result = extend(agent, start + timedelta(hours=2, seconds=42, microseconds=7))

        assert result is not None and result.ends_at == start + timedelta(hours=2)

    def test_same_end_again_is_a_no_op(self, agent, running, start):  # E7
        extend(agent, start + timedelta(hours=2))
        modified = BenchBooking.objects.values_list("modified", flat=True).get(pk=running.pk)

        assert extend(agent, start + timedelta(hours=2)) is not None
        assert BenchBooking.objects.values_list("modified", flat=True).get(pk=running.pk) == modified

    def test_can_extend_more_than_once(self, agent, running, start):
        extend(agent, start + timedelta(hours=2))
        extend(agent, start + timedelta(hours=3))

        assert ends_at_of(running) == start + timedelta(hours=3)

    def test_up_to_four_hours_in_total(self, agent, running, start):  # E5
        assert extend(agent, start + timedelta(hours=4)) is not None
        assert BenchBooking.objects.values_list("approval_status", flat=True).get(pk=running.pk) == "approved"

    def test_extended_booking_can_still_be_checked_in(self, agent, running, start):  # O21 not broken
        extend(agent, start + timedelta(hours=4))

        again = check_in_agent_booking(
            CheckInAgentBookingInput(agent_uid=agent.agent_uid, booking_code="BK-EXT"), actor=None
        )
        assert again is not None and again.ends_at == start + timedelta(hours=4)


@pytest.mark.django_db
class TestRefusals:
    def test_beyond_four_hours_needs_approval(self, agent, running, start):
        with pytest.raises(AgentExtensionNotAllowed) as error:
            extend(agent, start + timedelta(hours=4, minutes=1))

        assert refusal(error) == ("needs_approval", start + timedelta(hours=4))
        assert ends_at_of(running) == start + timedelta(minutes=90)

    def test_no_room_left_needs_approval(self, agent, running, start):
        BenchBooking.objects.filter(pk=running.pk).update(ends_at=start + timedelta(hours=3, minutes=55))

        with pytest.raises(AgentExtensionNotAllowed) as error:
            extend(agent, start + timedelta(hours=4))

        assert refusal(error) == ("needs_approval", start + timedelta(hours=4))

    def test_at_least_ten_minutes(self, agent, running, start):  # E6
        with pytest.raises(AgentExtensionNotAllowed) as error:
            extend(agent, start + timedelta(minutes=99))

        assert refusal(error) == ("too_short", start + timedelta(minutes=100))
        assert extend(agent, start + timedelta(minutes=100)) is not None

    def test_shortening_is_not_extension(self, agent, running, start):  # E2
        with pytest.raises(AgentExtensionNotAllowed) as error:
            extend(agent, start + timedelta(minutes=60))

        assert refusal(error) == ("not_later", None)

    def test_after_the_end_it_is_too_late(self, agent, running, start):  # E3
        with pytest.raises(AgentExtensionNotAllowed) as error:
            extend(agent, start + timedelta(hours=2), now=start + timedelta(minutes=90))

        assert refusal(error) == ("already_ended", None)

    def test_next_booking_blocks_the_extension(self, agent, running, start, make_booking):  # E4
        next_start = start + timedelta(hours=2)
        make_booking(starts_at=next_start, ends_at=next_start + timedelta(hours=1), code="BK-NEXT")

        with pytest.raises(AgentExtensionBenchNotFree) as error:
            extend(agent, start + timedelta(hours=3))

        assert error.value.details == {"available_until": next_start}
        assert extend(agent, next_start) is not None  # ending exactly when the next one starts is fine

    def test_bench_not_in_service(self, agent, running, start, bench):
        Bench.all_objects.filter(pk=bench.pk).update(lifecycle_status="retired")

        with pytest.raises(AgentExtensionNotAllowed) as error:
            extend(agent, start + timedelta(hours=2))

        assert refusal(error) == ("bench_not_in_service", None)

    def test_bench_downtime_in_the_extension(self, agent, running, start, bench):
        from core.labs.models import ResourceDowntime

        ResourceDowntime.for_new_resource(
            bench, condition="out_of_service", starts_at=start + timedelta(hours=1, minutes=30)
        ).save()

        with pytest.raises(AgentExtensionNotAllowed) as error:
            extend(agent, start + timedelta(hours=2))

        assert refusal(error) == ("bench_unavailable", None)


@pytest.mark.django_db
class TestNotEligible:  # E1: same silent None as check-in and end
    @pytest.mark.parametrize("status", [BookingStatus.RESERVED, BookingStatus.COMPLETED, BookingStatus.CANCELLED])
    def test_only_in_progress(self, agent, make_booking, start, status):
        make_booking(
            starts_at=start + timedelta(hours=1), ends_at=start + timedelta(hours=2), status=status, code="BK-EXT"
        )

        assert extend(agent, start + timedelta(hours=3)) is None

    @pytest.mark.parametrize("approval", [BookingApprovalStatus.PENDING, BookingApprovalStatus.REJECTED])
    def test_only_approved(self, agent, running, start, approval):
        reason = "Rejected in test setup" if approval == BookingApprovalStatus.REJECTED else ""
        BenchBooking.objects.filter(pk=running.pk).update(approval_status=approval, rejection_reason=reason)

        assert extend(agent, start + timedelta(hours=2)) is None

    def test_other_bench(self, running, start, other_bench):
        assert extend(make_agent(other_bench), start + timedelta(hours=2)) is None

    @pytest.mark.parametrize("code", ["BK-UNKNOWN", "", "  "])
    def test_unknown_code(self, agent, running, start, code):
        assert extend(agent, start + timedelta(hours=2), code=code) is None
        assert ends_at_of(running) == start + timedelta(minutes=90)


@pytest.mark.django_db(transaction=True)
def test_extension_and_a_new_booking_cannot_both_take_the_same_time(bench, make_booking, actor, start):
    agent = make_agent(bench)
    running = make_booking(
        starts_at=start, ends_at=start + timedelta(minutes=90), status=BookingStatus.IN_PROGRESS, code="BK-EXT"
    )
    barrier = Barrier(2)
    outcomes: dict[str, object] = {}

    def run_extend():
        try:
            barrier.wait(timeout=5)
            outcomes["extend"] = extend(agent, start + timedelta(hours=3))
        except Exception as error:
            outcomes["extend"] = error
        finally:
            connection.close()

    def run_create():
        try:
            barrier.wait(timeout=5)
            outcomes["create"] = create_bench_booking(
                actor=actor,
                data=CreateBenchBookingInput(
                    bench_id=bench.pk,
                    starts_at=start + timedelta(hours=2),
                    ends_at=start + timedelta(hours=2, minutes=30),
                ),
            )
        except Exception as error:
            outcomes["create"] = error
        finally:
            connection.close()

    threads = [Thread(target=run_extend), Thread(target=run_create)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    extended = outcomes["extend"] is not None and not isinstance(outcomes["extend"], Exception)
    created = isinstance(outcomes["create"], BenchBooking)
    assert extended != created, outcomes  # exactly one wins
    if extended:
        assert isinstance(outcomes["create"], BenchBookingConflict)
        assert ends_at_of(running) == start + timedelta(hours=3)
    else:
        assert isinstance(outcomes["extend"], AgentExtensionBenchNotFree)
        assert ends_at_of(running) == start + timedelta(minutes=90)
