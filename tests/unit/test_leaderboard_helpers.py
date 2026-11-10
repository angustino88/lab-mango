"""Unit tests for leaderboard helper functions — pure logic, no DB access."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from core.labs.features.leaderboard.helpers import (
    calculate_downtime_minutes,
    calculate_late_rate_from_tuples,
    clamp,
    count_weekdays,
    get_cache_timeout,
    parse_date_range,
)
from django.utils import timezone
from rest_framework.exceptions import ValidationError

_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class TestCountWeekdays:
    def test_single_monday(self):
        dt = datetime(2026, 4, 20, tzinfo=_TZ)
        assert count_weekdays(dt, dt) == 1

    def test_full_workweek(self):
        start = datetime(2026, 4, 20, tzinfo=_TZ)
        end = datetime(2026, 4, 24, tzinfo=_TZ)
        assert count_weekdays(start, end) == 5

    def test_weekend_only_returns_zero(self):
        start = datetime(2026, 4, 18, tzinfo=_TZ)
        end = datetime(2026, 4, 19, tzinfo=_TZ)
        assert count_weekdays(start, end) == 0

    def test_two_full_weeks(self):
        start = datetime(2026, 4, 13, tzinfo=_TZ)
        end = datetime(2026, 4, 24, tzinfo=_TZ)
        assert count_weekdays(start, end) == 10

    def test_single_weekend_day(self):
        sat = datetime(2026, 4, 18, tzinfo=_TZ)
        assert count_weekdays(sat, sat) == 0


class TestClamp:
    def test_midrange_unchanged(self):
        assert clamp(0.5) == 0.5

    def test_boundaries(self):
        assert clamp(0.0) == 0.0
        assert clamp(1.0) == 1.0

    def test_below_zero_clamps(self):
        assert clamp(-0.5) == 0.0

    def test_above_one_clamps(self):
        assert clamp(1.5) == 1.0

    def test_non_numeric_returns_zero(self):
        assert clamp(None) == 0.0
        assert clamp("bad") == 0.0

    def test_large_negative(self):
        assert clamp(-100.0) == 0.0

    def test_large_positive(self):
        assert clamp(999.0) == 1.0


class TestCalculateDowntimeMinutes:
    def test_empty_logs_returns_zero(self):
        start = datetime(2026, 4, 1, 8, 0, tzinfo=_TZ)
        end = datetime(2026, 4, 1, 18, 0, tzinfo=_TZ)
        assert calculate_downtime_minutes([], start, end) == 0.0

    def test_log_fully_within_window(self):
        start = datetime(2026, 4, 1, 8, 0, tzinfo=_TZ)
        end = datetime(2026, 4, 1, 18, 0, tzinfo=_TZ)
        log = {
            "offline_start": datetime(2026, 4, 1, 9, 0, tzinfo=_TZ),
            "offline_end": datetime(2026, 4, 1, 10, 0, tzinfo=_TZ),
        }
        assert calculate_downtime_minutes([log], start, end) == 60.0

    def test_log_clamped_to_window_start(self):
        start = datetime(2026, 4, 1, 8, 0, tzinfo=_TZ)
        end = datetime(2026, 4, 1, 12, 0, tzinfo=_TZ)
        log = {
            "offline_start": datetime(2026, 4, 1, 6, 0, tzinfo=_TZ),
            "offline_end": datetime(2026, 4, 1, 10, 0, tzinfo=_TZ),
        }
        assert calculate_downtime_minutes([log], start, end) == 120.0

    def test_none_offline_end_uses_window_end(self):
        start = datetime(2026, 4, 1, 8, 0, tzinfo=_TZ)
        end = datetime(2026, 4, 1, 10, 0, tzinfo=_TZ)
        log = {
            "offline_start": datetime(2026, 4, 1, 9, 0, tzinfo=_TZ),
            "offline_end": None,
        }
        assert calculate_downtime_minutes([log], start, end) == 60.0

    def test_multiple_logs_summed(self):
        start = datetime(2026, 4, 1, 8, 0, tzinfo=_TZ)
        end = datetime(2026, 4, 1, 18, 0, tzinfo=_TZ)
        logs = [
            {
                "offline_start": datetime(2026, 4, 1, 9, 0, tzinfo=_TZ),
                "offline_end": datetime(2026, 4, 1, 10, 0, tzinfo=_TZ),
            },
            {
                "offline_start": datetime(2026, 4, 1, 14, 0, tzinfo=_TZ),
                "offline_end": datetime(2026, 4, 1, 15, 0, tzinfo=_TZ),
            },
        ]
        assert calculate_downtime_minutes(logs, start, end) == 120.0

    def test_log_entirely_outside_window(self):
        start = datetime(2026, 4, 1, 8, 0, tzinfo=_TZ)
        end = datetime(2026, 4, 1, 10, 0, tzinfo=_TZ)
        log = {
            "offline_start": datetime(2026, 4, 1, 11, 0, tzinfo=_TZ),
            "offline_end": datetime(2026, 4, 1, 12, 0, tzinfo=_TZ),
        }
        assert calculate_downtime_minutes([log], start, end) == 0.0


class TestGetCacheTimeout:
    def test_less_than_7_days_returns_3600(self):
        start = datetime(2026, 4, 1, tzinfo=_TZ)
        end = datetime(2026, 4, 6, tzinfo=_TZ)
        assert get_cache_timeout(start, end) == 3600

    def test_7_or_more_days_returns_86400(self):
        start = datetime(2026, 4, 1, tzinfo=_TZ)
        end = datetime(2026, 4, 8, tzinfo=_TZ)
        assert get_cache_timeout(start, end) == 86400

    def test_exact_7_days(self):
        start = datetime(2026, 4, 1, tzinfo=_TZ)
        end = datetime(2026, 4, 8, tzinfo=_TZ)
        assert get_cache_timeout(start, end) == 86400


class TestParseDateRange:
    def _req(self, params: dict) -> MagicMock:
        r = MagicMock()
        r.query_params = params
        return r

    def test_valid_params_parsed(self):
        baseline = datetime(2026, 1, 1, tzinfo=_TZ)
        start, end = parse_date_range(
            self._req({"start_date": "2026-04-01", "end_date": "2026-04-30"}),
            baseline,
        )
        assert start.date().isoformat() == "2026-04-01"
        assert end.date().isoformat() == "2026-04-30"

    def test_invalid_format_raises_validation_error(self):
        baseline = datetime(2026, 1, 1, tzinfo=_TZ)
        with pytest.raises(ValidationError):
            parse_date_range(self._req({"start_date": "not-a-date"}), baseline)

    def test_no_params_uses_baseline_and_now(self):
        baseline = datetime(2026, 1, 1, tzinfo=_TZ)
        start, end = parse_date_range(self._req({}), baseline)
        assert start == baseline
        assert (timezone.now() - end).total_seconds() < 5

    def test_range_exceeding_730_days_raises(self):
        baseline = datetime(2026, 1, 1, tzinfo=_TZ)
        with pytest.raises(ValidationError):
            parse_date_range(
                self._req({"start_date": "2020-01-01", "end_date": "2026-04-30"}),
                baseline,
            )


class TestCalculateLateRateFromTuples:
    def test_empty_returns_zero(self):
        assert calculate_late_rate_from_tuples([]) == 0

    def test_session_fully_in_late_hours_returns_one(self):
        login = datetime(2026, 4, 1, 21, 0, tzinfo=_TZ)
        logout = datetime(2026, 4, 1, 23, 0, tzinfo=_TZ)
        assert calculate_late_rate_from_tuples([(login, logout)]) == 1.0

    def test_session_fully_in_day_hours_returns_zero(self):
        login = datetime(2026, 4, 1, 8, 0, tzinfo=_TZ)
        logout = datetime(2026, 4, 1, 17, 0, tzinfo=_TZ)
        assert calculate_late_rate_from_tuples([(login, logout)]) == 0.0

    def test_zero_duration_session_ignored(self):
        now = datetime(2026, 4, 1, 10, 0, tzinfo=_TZ)
        assert calculate_late_rate_from_tuples([(now, now)]) == 0

    def test_mixed_sessions(self):
        sessions = [
            # 2h daytime (0% late)
            (datetime(2026, 4, 1, 8, 0, tzinfo=_TZ), datetime(2026, 4, 1, 10, 0, tzinfo=_TZ)),
            # 2h nighttime (100% late)
            (datetime(2026, 4, 1, 21, 0, tzinfo=_TZ), datetime(2026, 4, 1, 23, 0, tzinfo=_TZ)),
        ]
        rate = calculate_late_rate_from_tuples(sessions)
        assert 0.4 <= rate <= 0.6  # ~50% late
