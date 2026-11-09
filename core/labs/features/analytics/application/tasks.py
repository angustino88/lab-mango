"""Scheduled Celery tasks for periodic analytics aggregation and alerts."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db.models import F
from django.utils import timezone

from core.labs.models import (
    ActiveLaboratoryObservation,
    ActiveUserObservation,
    AnalyticsGranularity,
    AnalyticsSource,
    Bench,
    BenchBooking,
    BookingVolumeObservation,
    LaboratoryVisitEvent,
    StorageQuotaMeasurement,
    VisitorVolumeObservation,
)
from core.users.models.lab_management_email import LabManagementEmail

from .notifications import (
    send_storage_quota_management_email,
    send_storage_quota_user_email,
)

logger = logging.getLogger(__name__)


@shared_task(name='labs.analytics.snapshot_daily_booking_volume')
def snapshot_daily_booking_volume() -> None:
    """Snapshot total booking volume created during the current calendar day."""
    now = timezone.localtime(timezone.now())
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    count = BenchBooking.objects.filter(created__gte=start_of_day, created__lt=end_of_day).count()
    BookingVolumeObservation.objects.update_or_create(
        period_start=start_of_day,
        period_end=end_of_day,
        granularity=AnalyticsGranularity.DAILY,
        source=AnalyticsSource.APPLICATION,
        defaults={"recorded_at": now, "booking_count": count},
    )


@shared_task(name='labs.analytics.snapshot_daily_active_benches')
def snapshot_daily_active_benches() -> None:
    """Snapshot the total number of non-deleted active benches."""
    now = timezone.localtime(timezone.now())
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    count = Bench.objects.filter(deleted_at__isnull=True).count()
    ActiveLaboratoryObservation.objects.update_or_create(
        period_start=start_of_day,
        period_end=end_of_day,
        granularity=AnalyticsGranularity.DAILY,
        source=AnalyticsSource.APPLICATION,
        defaults={"recorded_at": now, "active_laboratory_count": count},
    )


@shared_task(name='labs.analytics.snapshot_daily_active_users')
def snapshot_daily_active_users() -> None:
    """Snapshot the count of active platform users for the current day."""
    from core.users.models import User

    now = timezone.localtime(timezone.now())
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    count = User.objects.filter(is_active=True).count()
    ActiveUserObservation.objects.update_or_create(
        period_start=start_of_day,
        period_end=end_of_day,
        granularity=AnalyticsGranularity.DAILY,
        source=AnalyticsSource.APPLICATION,
        defaults={"recorded_at": now, "active_user_count": count},
    )


@shared_task(name='labs.analytics.snapshot_daily_facility_visitors')
def snapshot_daily_facility_visitors() -> None:
    """Snapshot distinct users visiting facilities during the current calendar day."""
    now = timezone.localtime(timezone.now())
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    count = (
        LaboratoryVisitEvent.objects.filter(occurred_at__gte=start_of_day, occurred_at__lt=end_of_day)
        .values("visitor")
        .distinct()
        .count()
    )
    VisitorVolumeObservation.objects.update_or_create(
        period_start=start_of_day,
        period_end=end_of_day,
        granularity=AnalyticsGranularity.DAILY,
        source=AnalyticsSource.APPLICATION,
        defaults={"recorded_at": now, "distinct_visitor_count": count},
    )


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
