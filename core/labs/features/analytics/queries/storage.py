"""Read-only queries for computing asset storage capacity and utilization."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import F

from core.labs.models import StorageQuotaMeasurement


def list_storage_quota_measurements(
    *,
    log_date: datetime | None = None,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Retrieve storage quota measurements with calculated utilization metrics."""
    queryset = StorageQuotaMeasurement.objects.all()
    if log_date:
        queryset = queryset.filter(measured_at__date=log_date.date())

    if top_n is not None and top_n > 0:
        queryset = queryset[:top_n]

    results = []
    for item in queryset:
        results.append({
            "username": item.account_identifier,
            "account_identifier": item.account_identifier,
            "account_display_name": item.account_display_name,
            "computer_identifier": item.computer_identifier,
            "used": float(item.used_gibibytes),
            "used_gibibytes": float(item.used_gibibytes),
            "quota": float(item.quota_gibibytes),
            "quota_gibibytes": float(item.quota_gibibytes),
            "utilization_percent": float(item.utilization_percent),
            "measured_at": item.measured_at,
        })
    return results


def get_exceeded_storage_quotas() -> list[StorageQuotaMeasurement]:
    """Retrieve storage measurements exceeding allocation quota."""
    return list(
        StorageQuotaMeasurement.objects.filter(
            quota_gibibytes__gt=0,
            used_gibibytes__gt=F("quota_gibibytes"),
        )
    )


__all__ = [
    "get_exceeded_storage_quotas",
    "list_storage_quota_measurements",
]
