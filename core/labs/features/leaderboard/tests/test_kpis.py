"""KPI definitions of the persona and lab leaderboards (docs/architecture.md section 5)."""

from datetime import datetime
from datetime import timezone as dt_timezone

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.labs.features.leaderboard.public import compute_leaderboard_lab, compute_leaderboard_persona
from core.labs.models import BookingApprovalStatus, BookingStatus, SessionAccessType
from tests.factories import (
    BenchBookingFactory,
    BenchFactory,
    LabProjectFactory,
    LabSessionLogFactory,
    UserFactory,
)

START = datetime(2026, 4, 6, 0, 0, tzinfo=dt_timezone.utc)  # Monday
END = datetime(2026, 4, 10, 23, 59, tzinfo=dt_timezone.utc)  # Friday: 5 weekdays


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 4, day, hour, minute, tzinfo=dt_timezone.utc)


def booking(owner, bench, day, start_hour, end_hour, **values):
    return BenchBookingFactory(
        bench=bench,
        requester=owner,
        starts_at=at(day, start_hour),
        ends_at=at(day, end_hour),
        status=values.pop("status", BookingStatus.COMPLETED),
        **values,
    )


def booked_session(owner, slot, login, logout, **values):
    return LabSessionLogFactory(
        user=owner,
        remote_user=owner.username,
        bench=slot.bench,
        booking=slot,
        booking_code=slot.booking_code,
        access_type=SessionAccessType.BOOKED,
        login_time=login,
        logout_time=logout,
        **values,
    )


def row_for(rows, pk):
    return next(row for row in rows if row["id"] == pk)


@pytest.mark.django_db
def test_booking_kpis_measure_attendance_use_of_slot_and_adherence():
    user = UserFactory(username="kpi-alice")
    bench = BenchFactory()
    attended = booking(user, bench, 7, 8, 12, project=LabProjectFactory(project_name="Apollo"))
    booking(user, bench, 8, 8, 12, status=BookingStatus.EXPIRED, project=None)  # a no-show
    booking(user, bench, 9, 8, 12, status=BookingStatus.CANCELLED)  # not expected: ignored
    booking(user, bench, 9, 13, 14, approval_status=BookingApprovalStatus.PENDING)  # not approved: ignored
    # Logged in 30 min early, left at 11:00: 3 h inside the 4 h slot, 0.5 h outside.
    booked_session(user, attended, at(7, 7, 30), at(7, 11), active_duration_seconds=3 * 3600)

    row = row_for(compute_leaderboard_persona(START, END), user.pk)

    assert row["total_bookings"] == 2
    assert row["no_show_bookings"] == 1
    assert row["booking_compliance"] == 0.5
    assert row["booking_utilization"] == round(3 / 8, 2)  # 3 h used of 8 h booked
    assert row["slot_adherence"] == round(3 / 3.5, 2)
    assert row["active_rate"] == round(3 / 3.5, 2)
    assert row["ad_hoc_rate"] == 0.0
    assert row["active_usage_minutes"] == 180.0
    assert row["total_usage_minutes"] == 210.0
    assert row["top_projects"] == ["Apollo"]


@pytest.mark.django_db
def test_no_bookings_is_not_full_compliance():
    user = UserFactory(username="kpi-adhoc")
    LabSessionLogFactory(user=user, remote_user=user.username, login_time=at(7, 9), logout_time=at(7, 10))

    row = row_for(compute_leaderboard_persona(START, END), user.pk)

    assert row["booking_compliance"] is None
    assert row["booking_utilization"] is None
    assert row["slot_adherence"] is None
    assert row["ad_hoc_rate"] == 1.0


@pytest.mark.django_db
def test_sessions_count_for_the_resolved_user_whatever_the_login_spelling():
    user = UserFactory(username="kpi-bob")
    LabSessionLogFactory(user=user, remote_user="CORP\\KPI-BOB", login_time=at(7, 9), logout_time=at(7, 10))
    LabSessionLogFactory(user=None, remote_user="corp\\Kpi-Bob", login_time=at(8, 9), logout_time=at(8, 10))

    assert row_for(compute_leaderboard_persona(START, END), user.pk)["total_sessions"] == 2


@pytest.mark.django_db
def test_rfo_rfh_detection_is_unchanged():
    user = UserFactory(username="kpi-rfo")
    for day in (6, 7, 8):  # 3 sessions over 5 weekdays: 3 / (5 * 2)
        LabSessionLogFactory(user=user, remote_user=user.username, login_time=at(day, 9), logout_time=at(day, 10))

    row = row_for(compute_leaderboard_persona(START, END), user.pk)

    assert (row["wfo_rate"], row["wfh_rate"]) == (0.3, 0.7)


@pytest.mark.django_db
def test_many_short_logins_do_not_outscore_a_full_booked_day():
    worker, clicker = UserFactory(username="kpi-worker"), UserFactory(username="kpi-clicker")
    slot = booking(worker, BenchFactory(), 7, 8, 16)
    booked_session(worker, slot, at(7, 8), at(7, 16))
    for minute in range(0, 40, 2):
        LabSessionLogFactory(
            user=clicker, remote_user=clicker.username, login_time=at(8, 9, minute), logout_time=at(8, 9, minute + 1)
        )

    rows = compute_leaderboard_persona(START, END)

    assert row_for(rows, worker.pk)["points"] > row_for(rows, clicker.pk)["points"]


@pytest.mark.django_db
def test_lab_kpis_use_the_bench_at_login_and_stay_at_four_queries():
    owner = UserFactory()
    bench = BenchFactory()
    slot = booking(owner, bench, 7, 8, 12)
    booking(owner, bench, 8, 8, 12, status=BookingStatus.EXPIRED)
    booked_session(owner, slot, at(7, 8), at(7, 12), active_duration_seconds=2 * 3600)
    LabSessionLogFactory(bench=bench, remote_user="guest", login_time=at(9, 9), logout_time=at(9, 10))
    for _ in range(5):
        BenchFactory()

    with CaptureQueriesContext(connection) as queries:
        rows = compute_leaderboard_lab(START, END)
    row = row_for(rows, bench.pk)

    assert len(queries.captured_queries) == 4  # benches, sessions, bookings, booked sessions
    assert row["total_sessions"] == 2
    assert row["active_users"] == 2
    assert row["total_usage_minutes"] == 180.0  # 2 h reported active + 1 h with no active figure
    assert row["utilization_rate"] == round(180 / (5 * 480), 2)
    assert row["booking_fill"] == round(480 / (5 * 480), 2)
    assert (row["total_bookings"], row["no_show_bookings"], row["booking_compliance"]) == (2, 1, 0.5)
    assert row["booking_utilization"] == 0.5  # 4 h used of 8 h booked
