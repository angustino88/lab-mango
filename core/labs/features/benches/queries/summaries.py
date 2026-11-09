"""Bench-owned lifecycle aggregates."""

from typing import Any

from core.common.queries.status_summary import status_summary
from core.labs.models import Bench


def get_bench_status_summary() -> dict[str, Any]:
    return status_summary(
        Bench.objects.filter(deleted_at__isnull=True),
        field="lifecycle_status", choices=Bench.LIFECYCLE_STATUSES,
    )
