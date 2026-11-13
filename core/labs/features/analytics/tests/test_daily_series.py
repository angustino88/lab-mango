"""Daily chart series for bookings, visitors, active users and active benches."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.analytics.public import (
    DEFAULT_DAILY_WINDOW_DAYS,
    MAX_DAILY_WINDOW_DAYS,
    aggregate_observation_buckets,
    get_active_bench_metrics,
    get_active_user_metrics,
    get_booking_volume_metrics,
    get_facility_visit_metrics,
    resolve_daily_window,
)
from core.labs.models import ActiveUserObservation, BenchBooking, BookingVolumeObservation, VisitorVolumeObservation
from tests.factories import (
    ActiveLaboratoryObservationFactory,
    ActiveUserObservationFactory,
    BenchBookingFactory,
    BenchFactory,
    BookingVolumeObservationFactory,
    LaboratoryVisitEventFactory,
    UserFactory,
    VisitorVolumeObservationFactory,
    grant_labs_role,
)

BASE = "/api/labs/analytics"


def _start(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min))


def _series(result: Any) -> list[dict[str, Any]]:
    """Narrow a metric selector result to its bucketed-list form."""
    assert isinstance(result, list)
    return result


def _daily(factory, day: date, **counts):
    return factory(period_start=_start(day), period_end=_start(day + timedelta(days=1)), **counts)


@pytest.fixture
def today() -> date:
    return timezone.localdate()


@pytest.fixture
def auth_client(db) -> APIClient:
    """These endpoints keep the labs default access: coordinators and admins."""
    client = APIClient()
    client.force_authenticate(user=grant_labs_role(UserFactory(), "coord"))
    return client


class TestResolveDailyWindow:
    def test_default_is_last_30_days_including_today(self):
        today = date(2026, 11, 13)
        assert resolve_daily_window(None, None, today=today) == (date(2026, 10, 15), date(2026, 11, 14))
        assert DEFAULT_DAILY_WINDOW_DAYS == 30

    def test_only_start_runs_to_today(self):
        assert resolve_daily_window(date(2026, 11, 1), None, today=date(2026, 11, 13)) == (
            date(2026, 11, 1),
            date(2026, 11, 14),
        )

    def test_only_end_goes_back_30_days(self):
        assert resolve_daily_window(None, date(2026, 3, 1), today=date(2026, 11, 13)) == (
            date(2026, 1, 30),
            date(2026, 3, 1),
        )

    @pytest.mark.parametrize(
        "after,before",
        [(date(2026, 11, 2), date(2026, 11, 2)), (date(2026, 11, 3), date(2026, 11, 2))],
    )
    def test_rejects_empty_window(self, after, before):
        with pytest.raises(ValueError):
            resolve_daily_window(after, before, today=date(2026, 11, 13))

    def test_maximum_span(self):
        start = date(2025, 1, 1)
        assert resolve_daily_window(start, start + timedelta(days=MAX_DAILY_WINDOW_DAYS), today=start)
        with pytest.raises(ValueError):
            resolve_daily_window(start, start + timedelta(days=MAX_DAILY_WINDOW_DAYS + 1), today=start)


@pytest.mark.django_db
class TestVolumeSeries:
    def test_default_window_is_continuous_zero_filled_and_counts_today_live(self, today):
        _daily(BookingVolumeObservationFactory, today - timedelta(days=3), booking_count=4)
        _daily(BookingVolumeObservationFactory, today - timedelta(days=40), booking_count=9)  # outside window
        BenchBookingFactory.create_batch(2)  # created today

        series = _series(get_booking_volume_metrics(unit="day"))

        assert [row["date"] for row in series] == [
            (today - timedelta(days=offset)).isoformat() for offset in range(DEFAULT_DAILY_WINDOW_DAYS - 1, -1, -1)
        ]
        counts = {row["date"]: row["count"] for row in series}
        assert counts[(today - timedelta(days=3)).isoformat()] == 4
        assert counts[today.isoformat()] == 2
        assert sum(counts.values()) == 6

    def test_today_snapshot_never_overrides_the_live_count(self, today):
        _daily(BookingVolumeObservationFactory, today, booking_count=99)

        series = get_booking_volume_metrics(unit="day", date_after=today)

        assert series == [{"date": today.isoformat(), "count": 0}]

    def test_future_days_are_omitted(self, today):
        series = _series(
            get_booking_volume_metrics(
                unit="day", date_after=today - timedelta(days=1), date_before=today + timedelta(days=5)
            )
        )
        assert [row["date"] for row in series] == [(today - timedelta(days=1)).isoformat(), today.isoformat()]

    def test_past_range_reads_only_observations(self, today, django_assert_num_queries):
        day = today - timedelta(days=20)
        _daily(VisitorVolumeObservationFactory, day, distinct_visitor_count=7)

        with django_assert_num_queries(1):
            series = get_facility_visit_metrics(unit="day", date_after=day, date_before=day + timedelta(days=2))

        assert series == [
            {"date": day.isoformat(), "count": 7},
            {"date": (day + timedelta(days=1)).isoformat(), "count": 0},
        ]

    def test_query_count_is_constant_for_the_longest_window(self, today, django_assert_num_queries):
        for offset in range(1, 6):
            _daily(BookingVolumeObservationFactory, today - timedelta(days=offset))
        with django_assert_num_queries(2):  # one aggregate + one live count for today
            series = _series(
                get_booking_volume_metrics(unit="day", date_after=today - timedelta(days=MAX_DAILY_WINDOW_DAYS - 1))
            )
        assert len(series) == MAX_DAILY_WINDOW_DAYS

    def test_today_visitors_are_distinct(self, today):
        visitor = UserFactory()
        LaboratoryVisitEventFactory.create_batch(3, visitor=visitor)
        LaboratoryVisitEventFactory(visitor=UserFactory())

        series = get_facility_visit_metrics(unit="day", date_after=today)

        assert series == [{"date": today.isoformat(), "count": 2}]


@pytest.mark.django_db
class TestWeeklyVisitorSummary:
    def test_counts_distinct_visitors_not_visit_events(self):
        now = timezone.now()
        regular, other = UserFactory(), UserFactory()
        LaboratoryVisitEventFactory.create_batch(4, visitor=regular, occurred_at=now - timedelta(days=1))
        LaboratoryVisitEventFactory(visitor=other, occurred_at=now - timedelta(days=6))
        LaboratoryVisitEventFactory(visitor=regular, occurred_at=now - timedelta(days=10))  # previous week

        assert get_facility_visit_metrics() == {"count": 2, "trend": 100}

    def test_trend_compares_distinct_visitors_week_over_week(self):
        now = timezone.now()
        visitors = UserFactory.create_batch(4)
        for visitor in visitors:
            LaboratoryVisitEventFactory.create_batch(2, visitor=visitor, occurred_at=now - timedelta(days=9))
        LaboratoryVisitEventFactory.create_batch(5, visitor=visitors[0], occurred_at=now - timedelta(hours=1))

        assert get_facility_visit_metrics() == {"count": 1, "trend": -75}


@pytest.mark.django_db
class TestPopulationSeries:
    def test_missing_days_are_omitted_and_today_is_live(self, today):
        _daily(ActiveLaboratoryObservationFactory, today - timedelta(days=2), active_laboratory_count=5)
        BenchFactory.create_batch(3)
        BenchFactory(deleted_at=timezone.now())

        series = get_active_bench_metrics(unit="day", date_after=today - timedelta(days=3))

        assert series == [
            {"date": (today - timedelta(days=2)).isoformat(), "count": 5},
            {"date": today.isoformat(), "count": 3},
        ]

    def test_today_user_total_is_live(self, today):
        UserFactory.create_batch(2, is_active=True)
        UserFactory(is_active=False)
        from core.users.models import User

        series = get_active_user_metrics(unit="day", date_after=today)

        assert series == [{"date": today.isoformat(), "count": User.objects.filter(is_active=True).count()}]

    def test_weekly_user_total_is_not_summed_across_snapshots(self):
        monday = date(2026, 11, 2)
        for offset, count in enumerate((10, 11, 12)):
            _daily(ActiveUserObservationFactory, monday + timedelta(days=offset), active_user_count=count)

        rows = list(aggregate_observation_buckets(ActiveUserObservation, "week"))

        assert [row["count"] for row in rows] == [12]


@pytest.mark.django_db
class TestBucketRange:
    def test_bounds_filter_by_local_day(self):
        for day in (date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 30), date(2026, 12, 1)):
            _daily(BookingVolumeObservationFactory, day, booking_count=1)

        rows = list(
            aggregate_observation_buckets(
                BookingVolumeObservation, "month", date_after=date(2026, 11, 1), date_before=date(2026, 12, 1)
            )
        )

        assert rows == [{"year": 2026, "month": 11, "count": 2}]


@pytest.mark.django_db
class TestDailySeriesHTTP:
    @pytest.mark.parametrize("name", ["booking", "lab-visits", "user-count", "lab-count"])
    def test_unit_day_returns_a_bounded_series(self, auth_client, today, name):
        response = auth_client.get(f"{BASE}/{name}", {"unit": "day"})

        assert response.status_code == 200
        data = response.json()["data"]
        assert isinstance(data, list)
        assert len(data) <= DEFAULT_DAILY_WINDOW_DAYS
        assert data[-1]["date"] == today.isoformat()

    def test_explicit_range(self, auth_client, today):
        _daily(BookingVolumeObservationFactory, today - timedelta(days=2), booking_count=3)

        response = auth_client.get(
            f"{BASE}/booking",
            {"unit": "day", "date_after": (today - timedelta(days=2)).isoformat(), "date_before": today.isoformat()},
        )

        assert response.json()["data"] == [
            {"date": (today - timedelta(days=2)).isoformat(), "count": 3},
            {"date": (today - timedelta(days=1)).isoformat(), "count": 0},
        ]

    @pytest.mark.parametrize(
        "params",
        [
            {"unit": "hour"},
            {"unit": "day", "date_after": "2020-01-01", "date_before": "2026-01-01"},
            {"unit": "day", "date_after": "not-a-date"},
            {"date_after": "2026-01-01"},
        ],
    )
    def test_invalid_query_returns_400(self, auth_client, params):
        response = auth_client.get(f"{BASE}/booking", params)

        assert response.status_code == 400

    def test_summary_without_unit_is_unchanged(self, auth_client):
        body = auth_client.get(f"{BASE}/booking").json()["data"]
        assert set(body) == {"count", "trend"}

    def test_requires_authentication(self, api_client):
        assert api_client.get(f"{BASE}/booking", {"unit": "day"}).status_code in (401, 403)

    def test_lab_members_without_a_staff_role_are_denied(self, api_client):
        api_client.force_authenticate(user=UserFactory())
        assert api_client.get(f"{BASE}/booking", {"unit": "day"}).status_code == 403


@pytest.mark.django_db
class TestBackfillCommand:
    def test_records_each_day_and_is_idempotent(self, today):
        day = today - timedelta(days=5)
        booking = BenchBookingFactory()
        BenchBooking.objects.filter(pk=booking.pk).update(created=_start(day) + timedelta(hours=8))
        LaboratoryVisitEventFactory(visitor=UserFactory(), occurred_at=_start(day) + timedelta(hours=8))

        for _ in range(2):
            call_command("backfill_analytics_daily_snapshots", since=day, until=day + timedelta(days=1))

        assert BookingVolumeObservation.objects.count() == 2
        assert BookingVolumeObservation.objects.get(period_start=_start(day)).booking_count == 1
        assert VisitorVolumeObservation.objects.get(period_start=_start(day)).distinct_visitor_count == 1

    @pytest.mark.parametrize("since_offset,until_offset", [(-1, 0), (3, 4), (MAX_DAILY_WINDOW_DAYS + 2, 1)])
    def test_rejects_invalid_ranges(self, today, since_offset, until_offset):
        with pytest.raises(CommandError):
            call_command(
                "backfill_analytics_daily_snapshots",
                since=today - timedelta(days=since_offset),
                until=today - timedelta(days=until_offset),
            )
