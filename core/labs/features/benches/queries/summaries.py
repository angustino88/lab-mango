"""Bench-owned status aggregates over the deprecated four-value ``status`` (computed, RS3)."""

from typing import Any

from core.common.queries.status_summary import status_summary
from core.labs.models import Bench
from core.labs.models.resource.base.availability import LEGACY_BENCH_STATUSES, legacy_bench_status_expression
from core.labs.models.resource.base.downtime import condition_expression


def get_bench_status_summary() -> dict[str, Any]:
    inventory = (
        Bench.objects.filter(deleted_at__isnull=True)
        .annotate(condition=condition_expression(Bench))
        .annotate(legacy_status=legacy_bench_status_expression())
    )
    return status_summary(inventory, field="legacy_status", choices=LEGACY_BENCH_STATUSES)
