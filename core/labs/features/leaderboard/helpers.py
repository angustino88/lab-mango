"""Pure helper functions for leaderboard analytics (no DB access)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

SHORT_RANGE_CACHE_TIMEOUT = 3600
LAB_CACHE_TIMEOUT = 86400


def _late_overlap_seconds(login_dt: datetime, logout_dt: datetime, tz: ZoneInfo) -> float:
    """Return seconds of [login_dt, logout_dt] that fall in 20:00–06:00 local time."""
    total = 0.0
    cur = login_dt.astimezone(tz).date()
    end_date = logout_dt.astimezone(tz).date()

    while cur <= end_date:
        w1_start = datetime(cur.year, cur.month, cur.day, 0, 0, 0, tzinfo=tz)
        w1_end = datetime(cur.year, cur.month, cur.day, 6, 0, 0, tzinfo=tz)
        s, e = max(login_dt, w1_start), min(logout_dt, w1_end)
        if e > s:
            total += (e - s).total_seconds()

        next_day = cur + timedelta(days=1)
        w2_start = datetime(cur.year, cur.month, cur.day, 20, 0, 0, tzinfo=tz)
        w2_end = datetime(next_day.year, next_day.month, next_day.day, 0, 0, 0, tzinfo=tz)
        s, e = max(login_dt, w2_start), min(logout_dt, w2_end)
        if e > s:
            total += (e - s).total_seconds()

        cur = next_day

    return total


def calculate_late_rate_from_tuples(session_tuples: list[tuple]) -> float:
    """Compute late rate from list of (login_time, logout_time) tuples."""
    tz = ZoneInfo(settings.TIME_ZONE)
    total_seconds = 0.0
    late_seconds = 0.0
    for login_time, logout_time in session_tuples:
        duration = (logout_time - login_time).total_seconds()
        if duration <= 0:
            continue
        total_seconds += duration
        late_seconds += _late_overlap_seconds(login_time, logout_time, tz)
    return round(late_seconds / total_seconds, 4) if total_seconds > 0 else 0


def calculate_downtime_minutes(offline_logs: list[dict], start: datetime, end: datetime) -> float:
    """Sum clamped duration (minutes) of offline logs within [start, end]."""
    total = 0.0
    for log in offline_logs:
        period_start = max(log["offline_start"], start)
        period_end = min(log["offline_end"] if log["offline_end"] else end, end)
        if period_end > period_start:
            total += (period_end - period_start).total_seconds() / 60
    return total


def count_weekdays(start: datetime, end: datetime) -> int:
    """Return number of Mon–Fri days in [start.date(), end.date()] inclusive."""
    return sum(
        1
        for i in range((end.date() - start.date()).days + 1)
        if (start.date() + timedelta(days=i)).weekday() < 5
    )


def get_cache_timeout(start: datetime, end: datetime) -> int:
    """Return 1h TTL for date ranges < 7 days, else LAB_CACHE_TIMEOUT."""
    return SHORT_RANGE_CACHE_TIMEOUT if (end - start).days < 7 else LAB_CACHE_TIMEOUT


def clamp(value: float) -> float:
    """Clamp a numeric value to [0.0, 1.0]."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def parse_date_range(request, baseline: datetime) -> tuple[datetime, datetime]:
    """Parse start_date/end_date query params; fallback to baseline→now."""
    local_tz = ZoneInfo(settings.TIME_ZONE)
    start_str = request.query_params.get("start_date")
    end_str = request.query_params.get("end_date")
    try:
        start = (
            datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=local_tz)
            if start_str
            else baseline
        )
        end = (
            datetime.strptime(end_str, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=local_tz
            )
            if end_str
            else timezone.now()
        )
    except ValueError:
        raise ValidationError("Invalid date format. Use YYYY-MM-DD.")
    if (end - start).days > 730:
        raise ValidationError("Date range must not exceed 730 days.")
    return start, end


__all__ = [
    "calculate_downtime_minutes",
    "calculate_late_rate_from_tuples",
    "clamp",
    "count_weekdays",
    "get_cache_timeout",
    "parse_date_range",
]
