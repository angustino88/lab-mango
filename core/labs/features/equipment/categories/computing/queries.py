"""Read-only queries for the live activity of computing equipment."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from core.labs.models import ComputingActivity, ComputingActivityStatus, Equipment


def computing_equipment():
    """Active units that carry a computing profile (category ``monitored``)."""
    return Equipment.objects.filter(deleted_at__isnull=True, computing_profile__isnull=False)


def get_computing_activity(equipment_id: int) -> ComputingActivity:
    """Return the activity of an active computing equipment record.

    A computer that has not reported yet has no row; an unsaved offline default is returned so
    readers get a stable shape without a write on GET. Raises ``Equipment.DoesNotExist``
    for a missing or soft-deleted computer.
    """
    computing = computing_equipment().select_related("activity").get(pk=equipment_id)
    try:
        return computing.activity
    except ComputingActivity.DoesNotExist:
        return ComputingActivity(computing=computing)


def computing_activity_projection(
    *, equipment_ids: Sequence[int], evaluated_at: datetime
) -> dict[int, dict[str, Any]]:
    """Batch safe live-state facts, without fetching remote identity or telemetry.

    Only units with a computing profile appear in the result. Missing activity is an
    offline read default, never persisted. Freshness does not change stored status.
    """
    rows = computing_equipment().filter(pk__in=equipment_ids).values(
        "pk",
        "activity__status",
        "activity__last_agent_report_at",
    )
    cutoff = evaluated_at - timedelta(minutes=10)
    result = {}
    for row in rows:
        status = row["activity__status"] or ComputingActivityStatus.OFFLINE
        heartbeat = row["activity__last_agent_report_at"]
        result[row["pk"]] = {
            "status": {"value": status, "label": str(ComputingActivityStatus(status).label)},
            "last_agent_report_at": heartbeat,
            "is_stale": heartbeat < cutoff if heartbeat is not None else None,
        }
    return result


__all__ = (
    "computing_activity_projection",
    "computing_equipment",
    "get_computing_activity",
)
