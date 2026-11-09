"""Technical SQL aggregation helpers; callers supply domain scope and choices."""

from collections.abc import Sequence
from typing import Any

from django.db.models import Count, Model, OuterRef, Q, QuerySet, Subquery


def with_latest_status(
    queryset: QuerySet, *, records: QuerySet, resource_field: str
) -> QuerySet:
    """Project the latest append-only state with a deterministic ID tiebreaker."""
    latest = records.filter(**{resource_field: OuterRef("pk")}).order_by("-created", "-id")
    return queryset.annotate(summary_status=Subquery(latest.values("status")[:1]))


def status_summary(
    queryset: QuerySet[Model], *, field: str, choices: Sequence[tuple[str, Any]]
) -> dict[str, Any]:
    """Count states in one query, including zero buckets and unknown values."""
    counts = queryset.order_by().aggregate(
        total_count=Count("pk"),
        **{
            f"status_{value}": Count("pk", filter=Q(**{field: value}))
            for value, _ in choices
        },
    )
    known_count = sum(counts[f"status_{value}"] for value, _ in choices)
    return {
        "total_count": counts["total_count"],
        "unknown_status_count": counts["total_count"] - known_count,
        "statuses": [
            {
                "status": {"value": value, "label": str(label)},
                "resource_count": counts[f"status_{value}"],
            }
            for value, label in choices
        ],
    }
