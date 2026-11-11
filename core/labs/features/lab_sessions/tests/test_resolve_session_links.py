"""A2: access type and booking, bench and user links, at ingestion and by backfill."""

import uuid
from dataclasses import replace
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.bench_bookings.public import SessionBookingFacts
from core.labs.features.lab_sessions.application import classify_access
from core.labs.features.lab_sessions.public import RecordSessionLogInput, record_session_log, resolve_session_links
from core.labs.models import (
    Bench,
    BenchBooking,
    BookingApprovalStatus,
    BookingStatus,
    EquipmentAssignment,
    LabSessionLog,
    SessionAccessType,
)
from core.users.tests.factories import UserFactory
from tests.factories import ComputingEquipmentFactory

NOW = timezone.now().replace(microsecond=0)
LOGIN = NOW - timedelta(hours=3)


BOOKING_FACTS = SessionBookingFacts(
    booking_id=7,
    bench_id=1,
    starts_at=LOGIN - timedelta(minutes=5),
    ends_at=LOGIN + timedelta(hours=2),
    status=BookingStatus.IN_PROGRESS,
    approval_status=BookingApprovalStatus.APPROVED,
)


def facts(**changes) -> SessionBookingFacts:
    return replace(BOOKING_FACTS, **changes)


class TestClassifyAccess:
    def test_no_code_is_ad_hoc(self):
        assert classify_access(booking_code=None, login_time=LOGIN, bench_id=1, booking=None) == (
            SessionAccessType.AD_HOC,
            None,
        )

    @pytest.mark.parametrize("status", [BookingStatus.IN_PROGRESS, BookingStatus.COMPLETED, BookingStatus.EXPIRED])
    def test_matching_booking_is_booked(self, status):
        assert classify_access(booking_code="BK", login_time=LOGIN, bench_id=1, booking=facts(status=status)) == (
            SessionAccessType.BOOKED,
            7,
        )

    def test_login_at_start_is_booked(self):
        booking = facts(starts_at=LOGIN)
        assert classify_access(booking_code="BK", login_time=LOGIN, bench_id=1, booking=booking)[0] == "booked"

    @pytest.mark.parametrize(
        ("bench_id", "login_time", "booking"),
        [
            (1, LOGIN, None),  # code matches no booking
            (2, LOGIN, facts()),  # another bench
            (None, LOGIN, facts()),  # computer was on no bench
            (1, None, facts()),  # no login time (legacy row)
            (1, LOGIN, facts(approval_status=BookingApprovalStatus.PENDING)),
            (1, LOGIN, facts(approval_status=BookingApprovalStatus.REJECTED)),
            (1, LOGIN, facts(status=BookingStatus.CANCELLED)),
            (1, LOGIN, facts(starts_at=LOGIN + timedelta(seconds=1))),  # before the start (O20)
            (1, LOGIN, facts(ends_at=LOGIN)),  # at the end (half-open window)
        ],
    )
    def test_anything_else_is_unverified(self, bench_id, login_time, booking):
        assert classify_access(booking_code="BK", login_time=login_time, bench_id=bench_id, booking=booking) == (
            SessionAccessType.UNVERIFIED_BOOKING,
            None,
        )


@pytest.fixture()
def bench(db):
    return Bench.objects.create(sku="LS-BENCH-A", name="Bench A")


@pytest.fixture()
def computer(bench):
    equipment = ComputingEquipmentFactory()
    EquipmentAssignment.objects.create(equipment=equipment, bench=bench, assigned_at=LOGIN - timedelta(days=1))
    return equipment


@pytest.fixture()
def booker(db):
    return UserFactory(username="nguyen.an")


@pytest.fixture()
def booking(bench, booker):
    booking = BenchBooking(
        bench=bench,
        starts_at=LOGIN - timedelta(minutes=5),
        ends_at=LOGIN + timedelta(hours=3),
        booking_code="BK-A2",
    )
    booking.save(actor=booker)
    return booking


def push(computer, **changes):
    values = {
        "equipment_id": computer.pk,
        "agent_id": "agent-a2",
        "event_id": uuid.uuid4(),
        "login_time": LOGIN,
        "logout_time": LOGIN + timedelta(hours=1),
        "active_duration_seconds": 3000.0,
        "remote_user": "nguyen.an",
        "booking_code": "BK-A2",
    }
    values.update(changes)
    record = record_session_log(RecordSessionLogInput(**values), actor=None, now=NOW)
    return record, LabSessionLog.objects.get(pk=record.id)


@pytest.mark.django_db
class TestLinksAtIngestion:
    def test_booked_session_links_booking_bench_and_user(self, computer, bench, booking, booker):
        record, stored = push(computer)

        assert record.access_type == SessionAccessType.BOOKED
        assert (stored.access_type, stored.booking_id) == (SessionAccessType.BOOKED, booking.pk)
        assert (stored.bench_id, stored.user_id) == (bench.pk, booker.pk)

    def test_ad_hoc_session_has_bench_and_user_but_no_booking(self, computer, bench, booker):
        record, stored = push(computer, booking_code=None)

        assert record.access_type == SessionAccessType.AD_HOC
        assert (stored.booking_id, stored.bench_id, stored.user_id) == (None, bench.pk, booker.pk)

    def test_unknown_code_is_unverified(self, computer, bench):
        record, stored = push(computer, booking_code="BK-NOPE")

        assert record.access_type == SessionAccessType.UNVERIFIED_BOOKING
        assert (stored.booking_id, stored.bench_id) == (None, bench.pk)

    def test_bench_is_the_placement_at_login_time(self, computer, bench, booking):
        moved_at = LOGIN + timedelta(minutes=30)
        EquipmentAssignment.objects.filter(equipment=computer).update(unassigned_at=moved_at)
        other = Bench.objects.create(sku="LS-BENCH-B", name="Bench B")
        EquipmentAssignment.objects.create(equipment=computer, bench=other, assigned_at=moved_at)

        _, stored = push(computer)

        assert stored.bench_id == bench.pk
        assert stored.access_type == SessionAccessType.BOOKED

    def test_booking_on_another_bench_is_unverified(self, computer, booker):
        elsewhere = Bench.objects.create(sku="LS-BENCH-C", name="Bench C")
        BenchBooking(
            bench=elsewhere,
            starts_at=LOGIN - timedelta(minutes=5),
            ends_at=LOGIN + timedelta(hours=1),
            booking_code="BK-ELSEWHERE",
        ).save(actor=booker)

        record, _ = push(computer, booking_code="BK-ELSEWHERE")

        assert record.access_type == SessionAccessType.UNVERIFIED_BOOKING

    def test_computer_on_no_bench_has_no_bench_link(self, booking):
        loose = ComputingEquipmentFactory()

        record, stored = push(loose)

        assert (record.access_type, stored.bench_id) == (SessionAccessType.UNVERIFIED_BOOKING, None)

    @pytest.mark.parametrize("login_name", ["nguyen.an", "NGUYEN.AN", "CORP\\nguyen.an", "  corp\\Nguyen.An "])
    def test_user_link_ignores_case_and_domain(self, computer, booker, login_name):
        _, stored = push(computer, booking_code=None, remote_user=login_name)

        assert stored.user_id == booker.pk
        assert stored.remote_user == login_name.strip()  # the pushed value is kept as sent

    def test_user_link_skips_unknown_inactive_and_ambiguous(self, computer, booker):
        UserFactory(username="gone.user", is_active=False)
        UserFactory(username="Twin")
        UserFactory(username="twin")

        for login_name in ("nobody", "gone.user", "TWIN"):
            _, stored = push(computer, booking_code=None, remote_user=login_name)
            assert stored.user_id is None, login_name

    def test_replay_keeps_the_stored_links(self, computer, booking):
        event_id = uuid.uuid4()
        first, _ = push(computer, event_id=event_id)
        BenchBooking.objects.filter(pk=booking.pk).update(status=BookingStatus.CANCELLED, cancellation_reason="x")

        again, stored = push(computer, event_id=event_id)

        assert (again.created, again.access_type) == (False, SessionAccessType.BOOKED)
        assert stored.booking_id == booking.pk

    def test_deleting_the_booking_keeps_the_session(self, computer, booking):
        _, stored = push(computer)

        BenchBooking.objects.filter(pk=booking.pk).delete()

        stored.refresh_from_db()
        assert (stored.access_type, stored.booking_id) == (SessionAccessType.BOOKED, None)


def legacy_row(computer, **changes) -> LabSessionLog:
    """A row stored before A2: no access type or links."""
    values = {
        "computing_equipment": computer,
        "agent_id": "legacy",
        "event_id": uuid.uuid4(),
        "reported_at": NOW,
        "login_time": LOGIN,
        "logout_time": LOGIN + timedelta(hours=1),
        "remote_user": "nguyen.an",
        "booking_code": "BK-A2",
    }
    values.update(changes)
    return LabSessionLog.objects.create(**values)


@pytest.mark.django_db
class TestConstraints:
    @pytest.mark.parametrize(
        "changes",
        [
            {"access_type": SessionAccessType.AD_HOC},  # ad hoc with a code
            {"access_type": SessionAccessType.BOOKED, "booking_code": None},
            {"access_type": SessionAccessType.UNVERIFIED_BOOKING, "booking_code": None},
            {"access_type": "walk_in"},  # not a choice: the database rejects it too
        ],
    )
    def test_access_type_must_match_the_code(self, computer, changes):
        row = legacy_row(computer)
        # A queryset update skips model validation, so this exercises the database guard itself.
        with pytest.raises(IntegrityError), transaction.atomic():
            LabSessionLog.objects.filter(pk=row.pk).update(**changes)

    @pytest.mark.parametrize("access_type", [SessionAccessType.UNVERIFIED_BOOKING, None])
    def test_only_booked_sessions_link_a_booking(self, computer, booking, access_type):
        row = legacy_row(computer)
        with pytest.raises(IntegrityError), transaction.atomic():
            LabSessionLog.objects.filter(pk=row.pk).update(access_type=access_type, booking=booking)


@pytest.mark.django_db
class TestBackfill:
    def test_fills_legacy_rows_once(self, computer, bench, booking, booker):
        booked = legacy_row(computer)
        ad_hoc = legacy_row(computer, booking_code=None, remote_user="unknown")
        no_times = legacy_row(computer, login_time=None, logout_time=None)
        already = legacy_row(computer, booking_code=None, access_type=SessionAccessType.AD_HOC)

        assert resolve_session_links(batch_size=2) == 3
        assert resolve_session_links() == 0

        for row in (booked, ad_hoc, no_times, already):
            row.refresh_from_db()
        assert (booked.access_type, booked.booking_id, booked.bench_id, booked.user_id) == (
            SessionAccessType.BOOKED,
            booking.pk,
            bench.pk,
            booker.pk,
        )
        assert (ad_hoc.access_type, ad_hoc.bench_id, ad_hoc.user_id) == (SessionAccessType.AD_HOC, bench.pk, None)
        assert (no_times.access_type, no_times.bench_id) == (SessionAccessType.UNVERIFIED_BOOKING, None)
        assert (already.bench_id, already.user_id) == (None, None)  # filled rows are never touched

    def test_max_batches_stops_early_and_resumes(self, computer):
        for _ in range(3):
            legacy_row(computer, booking_code=None)

        assert resolve_session_links(batch_size=1, max_batches=2) == 2
        assert LabSessionLog.objects.filter(access_type__isnull=True).count() == 1
        assert resolve_session_links(batch_size=1) == 1

    def test_batch_size_must_be_positive(self):
        with pytest.raises(ValueError):
            resolve_session_links(batch_size=0)

    def test_management_command(self, computer, capsys):
        legacy_row(computer, booking_code=None)

        call_command("backfill_session_links", "--batch-size", "10")

        assert "Filled 1 session log(s)." in capsys.readouterr().out
        assert not LabSessionLog.objects.filter(access_type__isnull=True).exists()
