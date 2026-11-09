"""Read-only queries for the live activity of computing equipment."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from core.labs.models import ComputingActivity, ComputingActivityStatus
from core.labs.models.resource.equipment.computing import ComputingEquipment


def get_computing_activity_by_sku(sku: str) -> ComputingActivity:
    """Return the activity of an active computing equipment record, looked up by SKU.

    A computer that has not reported yet has no row; an unsaved offline default is returned so
    readers get a stable shape without a write on GET. Raises ``ComputingEquipment.DoesNotExist``
    for a missing or soft-deleted computer.
    """
    computing = ComputingEquipment.objects.select_related("activity").get(sku=sku, deleted_at__isnull=True)
    try:
        return computing.activity
    except ComputingActivity.DoesNotExist:
        return ComputingActivity(computing=computing)


def get_computing_id_by_sku(sku: str) -> int:
    """Return the primary key of an active computing equipment record, looked up by SKU."""
    return ComputingEquipment.objects.values_list("pk", flat=True).get(sku=sku, deleted_at__isnull=True)


def computing_activity_projection(
    *, equipment_ids: Sequence[int], evaluated_at: datetime
) -> dict[int, dict[str, Any]]:
    """Batch safe live-state facts, without fetching remote identity or telemetry.

    Only actual computing subtypes appear in the result. Missing activity is an
    offline read default, never persisted. Freshness does not change stored status.
    """
    rows = ComputingEquipment.objects.filter(pk__in=equipment_ids, deleted_at__isnull=True).values(
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


__all__ = ("computing_activity_projection", "get_computing_activity_by_sku", "get_computing_id_by_sku")
