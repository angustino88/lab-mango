"""KPI assessment endpoints: coordinator/admin only; scorecard, rating, strengths, development areas, trend."""

from datetime import datetime
from datetime import timezone as dt_timezone

import pytest
from rest_framework.test import APIClient

from core.labs.models import BookingStatus, SessionAccessType
from tests.factories import BenchBookingFactory, BenchFactory, LabSessionLogFactory, UserFactory, grant_labs_role

RANGE = {"start_date": "2026-04-06", "end_date": "2026-04-10"}  # Mon-Fri; previous period is the week before


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 4, day, hour, minute, tzinfo=dt_timezone.utc)


def client_for(role: str) -> APIClient:
    api = APIClient()
    api.force_authenticate(user=grant_labs_role(UserFactory(), role))
    return api


def booked_day(user, bench, day, *, attend=True, active_hours=4):
    slot = BenchBookingFactory(
        bench=bench,
        requester=user,
        starts_at=at(day, 8),
        ends_at=at(day, 12),
        status=BookingStatus.COMPLETED if attend else BookingStatus.EXPIRED,
    )
    if attend:
        LabSessionLogFactory(
            user=user,
            remote_user=user.username,
            bench=bench,
            booking=slot,
            booking_code=slot.booking_code,
            access_type=SessionAccessType.BOOKED,
            login_time=at(day, 8),
            logout_time=at(day, 12),
            active_duration_seconds=active_hours * 3600,
        )
    return slot


@pytest.mark.django_db
def test_assessments_are_for_coordinators_and_admins_only():
    user, bench = UserFactory(), BenchFactory()
    member = client_for("user")
    assert member.get(f"/api/labs/leaderboard/users/{user.pk}/assessment", RANGE).status_code == 403
    assert member.get(f"/api/labs/benches/{bench.pk}/assessment", RANGE).status_code == 403
    # The rankings themselves stay visible to every lab member.
    assert member.get("/api/labs/leaderboard/persona", RANGE).status_code == 200

    coordinator = client_for("coord")
    assert coordinator.get(f"/api/labs/leaderboard/users/{user.pk}/assessment", RANGE).status_code == 200
    assert coordinator.get(f"/api/labs/benches/{bench.pk}/assessment", RANGE).status_code == 200
    assert coordinator.get("/api/labs/leaderboard/users/999999/assessment", RANGE).status_code == 404


@pytest.mark.django_db
def test_a_lab_member_reads_their_own_assessment_only():
    me = grant_labs_role(UserFactory(), "user")
    other = UserFactory()
    api = APIClient()
    api.force_authenticate(user=me)

    assert api.get(f"/api/labs/leaderboard/users/{me.pk}/assessment", RANGE).status_code == 200
    assert api.get(f"/api/labs/leaderboard/users/{other.pk}/assessment", RANGE).status_code == 403
    assert api.get(f"/api/labs/benches/{BenchFactory().pk}/assessment", RANGE).status_code == 403

    no_role = UserFactory()  # no Labs role: not even their own
    outsider = APIClient()
    outsider.force_authenticate(user=no_role)
    assert outsider.get(f"/api/labs/leaderboard/users/{no_role.pk}/assessment", RANGE).status_code == 403


@pytest.mark.django_db
def test_user_assessment_reports_strengths_development_areas_and_trend():
    user, bench = UserFactory(username="assess-alice"), BenchFactory()
    for day in (6, 7, 8, 9):  # four booked, fully used, focused days
        booked_day(user, bench, day)
    booked_day(user, bench, 10, attend=False)  # one no-show
    for day in (1, 2):  # previous week: two no-shows, one idle day
        booked_day(user, bench, day, attend=False)
    booked_day(user, bench, 3, active_hours=1)

    data = client_for("coord").get(f"/api/labs/leaderboard/users/{user.pk}/assessment", RANGE).json()["data"]

    kpis = {kpi["kpi"]["value"]: kpi for kpi in data["kpis"]}
    assert kpis["show_up_rate"]["value"] == 0.8
    assert kpis["show_up_rate"]["target"] == 0.9
    assert kpis["show_up_rate"]["status"]["value"] == "near"
    assert kpis["booking_utilization_rate"]["status"]["value"] == "met"
    assert kpis["active_time_ratio"]["value"] == 1.0
    assert "extended_hours_activity" not in kpis  # extended-hours work earns bonus points, not an assessment KPI

    strengths = [s["kpi"]["value"] for s in data["strengths"]]
    assert strengths[:2] == ["booking_utilization_rate", "active_time_ratio"]
    assert data["strengths"][0]["text"] == "Efficient use of reserved time: sessions covered 80% of booked time."

    area = data["development_areas"][0]
    assert area["kpi"]["value"] == "show_up_rate"
    assert area["text"] == "Show-up Rate is 80%: 1 of 5 bookings had no session (no-shows)."
    assert area["recommendation"].startswith("Cancel or shorten bookings")

    assert data["rating"]["value"] in {"exceeds", "meets"}
    assert data["previous_score"] is not None and data["score"] > data["previous_score"]
    assert data["summary"] == (
        f"Up {data['score'] - data['previous_score']} points on the previous period ({data['previous_score']}/100). "
        "Key strength: booking utilization rate. Main focus: show-up rate."
    )
    assert data["period"]["starts_at"].startswith("2026-04-06")


@pytest.mark.django_db
def test_too_little_activity_is_not_rated():
    user = UserFactory(username="assess-new")
    LabSessionLogFactory(user=user, remote_user=user.username, login_time=at(7, 9), logout_time=at(7, 10))

    data = client_for("coord").get(f"/api/labs/leaderboard/users/{user.pk}/assessment", RANGE).json()["data"]

    assert data["rating"]["value"] == "insufficient_data"
    assert data["score"] is None
    assert data["summary"] == "Not enough activity for a rating (1 sessions and 0 bookings in the period)."


@pytest.mark.django_db
def test_bench_assessment_flags_low_utilisation_with_a_recommendation():
    owner, bench = UserFactory(), BenchFactory()
    booked_day(owner, bench, 6, active_hours=1)
    for day in (7, 8):
        booked_day(owner, bench, day, attend=False)

    data = client_for("coord").get(f"/api/labs/benches/{bench.pk}/assessment", RANGE).json()["data"]

    areas = {area["kpi"]["value"]: area for area in data["development_areas"]}
    assert areas["bench_utilization_rate"]["severity"]["value"] == "below"
    assert areas["bench_utilization_rate"]["text"] == "Low utilisation: active 3% of working hours."
    assert "show_up_rate" in areas
    assert data["rating"]["value"] == "below"


@pytest.mark.django_db
def test_early_release_rate_credits_completing_the_booking_when_done():
    """4 h booked, used for 1 h, then either completed straight away or left reserved."""
    bench = BenchFactory()
    releaser, holder = UserFactory(username="assess-releaser"), UserFactory(username="assess-holder")
    for user, completed_at in ((releaser, at(6, 9)), (holder, at(6, 12))):
        slot = BenchBookingFactory(
            bench=bench if user is releaser else BenchFactory(),
            requester=user,
            starts_at=at(6, 8),
            ends_at=at(6, 12),
            status=BookingStatus.COMPLETED,
            completed_at=completed_at,
        )
        LabSessionLogFactory(
            user=user,
            remote_user=user.username,
            bench=slot.bench,
            booking=slot,
            booking_code=slot.booking_code,
            access_type=SessionAccessType.BOOKED,
            login_time=at(6, 8),
            logout_time=at(6, 9),
        )

    coordinator = client_for("coord")
    released = coordinator.get(f"/api/labs/leaderboard/users/{releaser.pk}/assessment", RANGE).json()["data"]
    held = coordinator.get(f"/api/labs/leaderboard/users/{holder.pk}/assessment", RANGE).json()["data"]

    def kpi(data, key):
        return next(k for k in data["kpis"] if k["kpi"]["value"] == key)

    # Booking utilisation is 25 % either way: over-booking is still visible.
    assert kpi(released, "booking_utilization_rate")["value"] == 0.25
    assert kpi(held, "booking_utilization_rate")["value"] == 0.25
    assert kpi(released, "early_release_rate")["value"] == 1.0
    assert kpi(held, "early_release_rate")["value"] == 0.0
    area = next(a for a in held["development_areas"] if a["kpi"]["value"] == "early_release_rate")
    assert (
        area["text"] == "Only 0% of unused booked time was released: 3 h stayed reserved after the last session ended."
    )


@pytest.mark.parametrize(("extended_hours_rate", "recognised"), [(0.0, False), (0.19, False), (0.20, True), (0.6, True)])
def test_extended_hours_activity_is_recognised_never_a_gap(extended_hours_rate, recognised):
    from core.labs.features.leaderboard.queries.assessment import EXTENDED_HOURS_RECOGNITION, PERSONA_KPIS, _assess

    row = {"total_sessions": 10, "total_bookings": 10, "extended_hours_rate": extended_hours_rate}
    result = _assess(PERSONA_KPIS, row, None, at(6, 0), at(10, 0), at(1, 0), EXTENDED_HOURS_RECOGNITION)

    keys = [s["kpi"] for s in result["strengths"]]
    assert ("extended_hours_activity" in keys) is recognised
    assert "extended_hours_activity" not in [a["kpi"] for a in result["development_areas"]]
    assert "extended_hours_activity" not in [k["kpi"] for k in result["kpis"]]
