"""License-owned status/category projections; no identifiers or financial data."""

from typing import Any

from django.db.models import Count, F, QuerySet

from core.common.queries.status_summary import status_summary, with_latest_status
from core.labs.models import License, LicenseStatus, LicenseStatusRecord


def get_license_status_summary() -> dict[str, Any]:
    inventory = with_latest_status(
        License.objects.filter(deleted_at__isnull=True),
        records=LicenseStatusRecord.objects.all(), resource_field="license_id",
    )
    return status_summary(inventory, field="summary_status", choices=LicenseStatus.choices)


def list_license_category_summary() -> QuerySet:
    return (
        License.objects.filter(deleted_at__isnull=True).order_by()
        .values(category_id_value=F("category_id"), category_name=F("category__name"))
        .annotate(resource_count=Count("pk"))
        .order_by("category_name", "category_id_value")
    )
