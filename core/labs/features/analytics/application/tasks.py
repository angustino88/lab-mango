"""Scheduled Celery tasks for periodic analytics aggregation and alerts."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from celery import shared_task
from django.conf import settings
from django.db.models import F
from django.utils import timezone

from core.labs.models import (
    ActiveLaboratoryObservation,
    ActiveUserObservation,
    AnalyticsGranularity,
    AnalyticsSource,
    BookingVolumeObservation,
    StorageQuotaMeasurement,
    VisitorVolumeObservation,
)
from core.users.models.lab_management_email import LabManagementEmail

from ..queries.calculations import local_day_start
from ..queries.observations import (
    count_active_benches,
    count_active_users,
    count_bookings_created,
    count_distinct_visitors,
)
from .notifications import (
    send_storage_quota_management_email,
    send_storage_quota_user_email,
)

logger = logging.getLogger(__name__)


def _snapshot_day(day: str | None) -> tuple[datetime, datetime]:
    """Return the local-day bounds to snapshot: ``day`` (ISO date) or, by default, yesterday.

    The schedule runs shortly after midnight, so the default records the day that just ended
    and never a partial day. ``day`` is a string because Celery serializes arguments as JSON.
    """
    target = date.fromisoformat(day) if day else timezone.localdate() - timedelta(days=1)
    return local_day_start(target), local_day_start(target + timedelta(days=1))


def _record(model: Any, start: datetime, end: datetime, **counts: int) -> None:
    # Race guard: the unique constraint on (period_start, period_end, granularity, source).
    # update_or_create makes a rerun or a concurrent duplicate overwrite the same row.
    model.objects.update_or_create(
        period_start=start,
        period_end=end,
        granularity=AnalyticsGranularity.DAILY,
        source=AnalyticsSource.APPLICATION,
        defaults={"recorded_at": timezone.now(), **counts},
    )


@shared_task(name='labs.analytics.snapshot_daily_booking_volume')
def snapshot_daily_booking_volume(day: str | None = None) -> None:
    """Record bookings created during one local day (default: yesterday). Safe to rerun."""
    start, end = _snapshot_day(day)
    _record(BookingVolumeObservation, start, end, booking_count=count_bookings_created(start, end))


@shared_task(name='labs.analytics.snapshot_daily_active_benches')
def snapshot_daily_active_benches() -> None:
    """Record the current non-deleted bench count as the total for the day that just ended.

    A population cannot be measured for a past day, so this task takes no ``day`` argument.
    """
    start, end = _snapshot_day(None)
    _record(ActiveLaboratoryObservation, start, end, active_laboratory_count=count_active_benches())


@shared_task(name='labs.analytics.snapshot_daily_active_users')
def snapshot_daily_active_users() -> None:
    """Record the current active user count as the total for the day that just ended.

    A population cannot be measured for a past day, so this task takes no ``day`` argument.
    """
    start, end = _snapshot_day(None)
    _record(ActiveUserObservation, start, end, active_user_count=count_active_users())


@shared_task(name='labs.analytics.snapshot_daily_facility_visitors')
def snapshot_daily_facility_visitors(day: str | None = None) -> None:
    """Record distinct facility visitors during one local day (default: yesterday). Safe to rerun."""
    start, end = _snapshot_day(day)
    _record(VisitorVolumeObservation, start, end, distinct_visitor_count=count_distinct_visitors(start, end))


@shared_task(name='labs.analytics.send_storage_quota_alerts')
def send_storage_quota_alerts() -> bool:
    """Audit storage quota compliance and dispatch warning emails for violations."""
    exceeded = list(
        StorageQuotaMeasurement.objects.filter(
            quota_gibibytes__gt=0,
            used_gibibytes__gt=F("quota_gibibytes"),
        )
    )
    if not exceeded:
        return True

    email_domain = getattr(settings, "EMAIL_USER_DOMAIN", "example.com")
    user_map = defaultdict(list)
    for measurement in exceeded:
        user_map[measurement.account_identifier].append(measurement)

    all_delivered = True
    for username, quotas in user_map.items():
        if not send_storage_quota_user_email(username, quotas, email_domain):
            all_delivered = False

    admin_emails = list(
        LabManagementEmail.objects.filter(is_active=True).values_list("email", flat=True)
    )
    mgmt_delivered = send_storage_quota_management_email(exceeded, admin_emails)

    return all_delivered and mgmt_delivered


__all__ = [
    "send_storage_quota_alerts",
    "snapshot_daily_active_benches",
    "snapshot_daily_active_users",
    "snapshot_daily_booking_volume",
    "snapshot_daily_facility_visitors",
]
