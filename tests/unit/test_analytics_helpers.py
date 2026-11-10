"""Unit tests for analytics helper functions."""
from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_timezone

import pytest

from core.labs.features.analytics.queries.calculations import (
    aggregate_observation_buckets as get_aggregated_logs,
)
from core.labs.features.analytics.queries.calculations import (
    calculate_official_working_hours as get_official_working_hours,
)
from core.labs.features.analytics.queries.calculations import (
    calculate_timeslot_distribution as extract_timeslots,
)
from core.labs.features.analytics.queries.calculations import (
    calculate_working_hours as get_working_hours,
)
from core.labs.features.analytics.queries.calculations import (
    get_nearest_monday as nearest_monday,
)
from core.labs.features.analytics.queries.calculations import (
    get_nearest_tuesday as nearest_tuesday,
)
from core.labs.models import (
    ActiveLaboratoryObservation,
    ActiveUserObservation,
    BookingVolumeObservation,
    VisitorVolumeObservation,
)

UTC = dt_timezone.utc


class TestGetWorkingHours:
    def test_same_datetime_returns_zero(self):
        dt = datetime(2024, 4, 1, 9, 0, tzinfo=UTC)
        assert get_working_hours(dt, dt) == 0.0

    def test_one_weekday_hour(self):
        start = datetime(2024, 4, 1, 9, 0, tzinfo=UTC)
        end = datetime(2024, 4, 1, 10, 0, tzinfo=UTC)
        assert get_working_hours(start, end) == pytest.approx(1.0)

    def test_skips_weekend(self):
        start = datetime(2024, 4, 5, 8, 0, tzinfo=UTC)  # Friday
        end = datetime(2024, 4, 8, 8, 0, tzinfo=UTC)    # Monday
        assert get_working_hours(start, end) == pytest.approx(24.0)  # Fri 8am-midnight + Mon midnight-8am

    def test_full_week_is_five_days(self):
        start = datetime(2024, 4, 1, 0, 0, tzinfo=UTC)
        end = datetime(2024, 4, 8, 0, 0, tzinfo=UTC)
        assert get_working_hours(start, end) == pytest.approx(5 * 24.0)


class TestGetOfficialWorkingHours:
    def test_outside_working_hours_returns_zero(self):
        start = datetime(2024, 4, 1, 6, 0, tzinfo=UTC)
        end = datetime(2024, 4, 1, 8, 0, tzinfo=UTC)
        assert get_official_working_hours(start, end) == pytest.approx(0.0)

    def test_within_working_hours(self):
        start = datetime(2024, 4, 1, 9, 0, tzinfo=UTC)
        end = datetime(2024, 4, 1, 17, 0, tzinfo=UTC)
        assert get_official_working_hours(start, end) == pytest.approx(8.0)

    def test_weekend_excluded(self):
        start = datetime(2024, 4, 6, 9, 0, tzinfo=UTC)  # Saturday
        end = datetime(2024, 4, 6, 17, 0, tzinfo=UTC)
        assert get_official_working_hours(start, end) == pytest.approx(0.0)


class TestExtractTimeslots:
    def test_returns_12_slots(self):
        start = datetime(2024, 4, 1, 0, 0, tzinfo=UTC)
        end = datetime(2024, 4, 1, 2, 0, tzinfo=UTC)
        assert len(extract_timeslots(start, end)) == 12

    def test_first_slot_captures_midnight_to_2am(self):
        start = datetime(2024, 4, 1, 0, 0, tzinfo=UTC)  # Monday
        end = datetime(2024, 4, 1, 2, 0, tzinfo=UTC)
        slots = extract_timeslots(start, end)
        assert slots[0] == pytest.approx(2.0)
        assert all(s == 0.0 for s in slots[1:])

    def test_skips_weekend(self):
        start = datetime(2024, 4, 6, 0, 0, tzinfo=UTC)  # Saturday
        end = datetime(2024, 4, 7, 0, 0, tzinfo=UTC)
        assert all(s == 0.0 for s in extract_timeslots(start, end))


@pytest.mark.django_db
class TestNearestMonday:
    def test_returns_midnight(self):
        result = nearest_monday()
        assert result.hour == 0 and result.minute == 0

    def test_weekday_is_monday(self):
        assert nearest_monday().weekday() == 0


@pytest.mark.django_db
class TestNearestTuesday:
    def test_returns_midnight(self):
        result = nearest_tuesday()
        assert result.hour == 0 and result.minute == 0

    def test_weekday_is_tuesday(self):
        assert nearest_tuesday().weekday() == 1


@pytest.mark.django_db
class TestGetAggregatedLogs:
    def test_raises_on_invalid_unit(self):
        with pytest.raises(ValueError):
            list(get_aggregated_logs(VisitorVolumeObservation, "invalid"))

    def test_day_unit_returns_queryset(self, db):
        from tests.factories import VisitorVolumeObservationFactory
        VisitorVolumeObservationFactory(distinct_visitor_count=10)
        result = list(get_aggregated_logs(VisitorVolumeObservation, "day"))
        assert len(result) >= 1
        assert "count" in result[0]

    def test_lab_change_log_uses_max(self, db):
        from tests.factories import ActiveLaboratoryObservationFactory
        ActiveLaboratoryObservationFactory(active_laboratory_count=5)
        ActiveLaboratoryObservationFactory(active_laboratory_count=8)
        result = list(get_aggregated_logs(ActiveLaboratoryObservation, "day"))
        assert result[0]["count"] == 8

    def test_non_lab_change_log_uses_sum(self, db):
        from tests.factories import BookingVolumeObservationFactory
        BookingVolumeObservationFactory(booking_count=3)
        BookingVolumeObservationFactory(booking_count=4)
        result = list(get_aggregated_logs(BookingVolumeObservation, "day"))
        total = sum(r["count"] for r in result)
        assert total == 7

    def test_week_unit(self, db):
        from tests.factories import ActiveUserObservationFactory
        ActiveUserObservationFactory(active_user_count=5)
        result = list(get_aggregated_logs(ActiveUserObservation, "week"))
        assert "count" in result[0]
