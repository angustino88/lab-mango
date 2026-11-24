"""Lifecycle counts for live benches."""

from typing import Any

from core.common.queries.status_summary import status_summary
from core.labs.models import Bench, ResourceLifecycleStatus


def get_bench_status_summary() -> dict[str, Any]:
    inventory = Bench.objects.filter(deleted_at__isnull=True)
    return status_summary(inventory, field="lifecycle_status", choices=ResourceLifecycleStatus.choices)
