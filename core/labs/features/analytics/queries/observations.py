"""Read-only queries for aggregate volume and population observations."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.utils import timezone

from core.labs.models import (
    ActiveLaboratoryObservation,
    ActiveUserObservation,
    Bench,
    BenchBooking,
    BookingVolumeObservation,
    LaboratoryVisitEvent,
    VisitorVolumeObservation,
)

from .calculations import aggregate_observation_buckets, calculate_period_trend


def get_booking_volume_metrics(*, unit: str | None = None) -> dict[str, Any] | list[dict[str, Any]]:
    """Retrieve booking volume trend or historical time-bucketed aggregates."""
    if unit:
        return list(aggregate_observation_buckets(BookingVolumeObservation, unit))

    now = timezone.now()
    this_week = now - timedelta(days=7)
    last_week = now - timedelta(days=14)

    current_count = BenchBooking.objects.filter(
        created__gte=this_week,
        created__lte=now,
    ).count()

    previous_count = BenchBooking.objects.filter(
        created__gte=last_week,
        created__lt=this_week,
    ).count()

    if current_count == 0 and previous_count == 0:
        obs = BookingVolumeObservation.objects.filter(period_start__gte=last_week)
        current_count = sum(o.booking_count for o in obs.filter(period_start__gte=this_week))
        previous_count = sum(o.booking_count for o in obs.filter(period_start__lt=this_week))

    trend = calculate_period_trend(previous_count, current_count)
    return {"count": current_count, "trend": trend}


def get_active_bench_metrics(*, unit: str | None = None) -> dict[str, Any] | list[dict[str, Any]]:
    """Retrieve active bench population count or historical bucketed snapshots."""
    if unit:
        return list(aggregate_observation_buckets(ActiveLaboratoryObservation, unit))

    count = Bench.objects.filter(deleted_at__isnull=True).count()
    if count == 0:
        latest = ActiveLaboratoryObservation.objects.order_by("-period_start").first()
        count = latest.active_laboratory_count if latest else 0

    return {"count": count, "trend": 0}


def get_active_user_metrics(*, unit: str | None = None) -> dict[str, Any] | list[dict[str, Any]]:
    """Retrieve active user count or historical bucketed snapshots."""
    if unit:
        return list(aggregate_observation_buckets(ActiveUserObservation, unit))

    User = get_user_model()
    count = User.objects.filter(is_active=True).count()
    if count == 0:
        latest = ActiveUserObservation.objects.order_by("-period_start").first()
        count = latest.active_user_count if latest else 0

    return {"count": count, "trend": 0}


def get_facility_visit_metrics(*, unit: str | None = None) -> dict[str, Any] | list[dict[str, Any]]:
    """Retrieve facility visit counts or historical bucketed visits."""
    if unit:
        return list(aggregate_observation_buckets(VisitorVolumeObservation, unit))

    now = timezone.now()
    this_week = now - timedelta(days=7)
    last_week = now - timedelta(days=14)

    current_count = LaboratoryVisitEvent.objects.filter(
        occurred_at__gte=this_week,
        occurred_at__lte=now,
    ).count()

    previous_count = LaboratoryVisitEvent.objects.filter(
        occurred_at__gte=last_week,
        occurred_at__lt=this_week,
    ).count()

    trend = calculate_period_trend(previous_count, current_count)
    return {"count": current_count, "trend": trend}


__all__ = [
    "get_active_bench_metrics",
    "get_active_user_metrics",
    "get_booking_volume_metrics",
    "get_facility_visit_metrics",
]
