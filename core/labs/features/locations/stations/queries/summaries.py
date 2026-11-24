"""Lifecycle counts for live stations."""

from typing import Any

from core.common.queries.status_summary import status_summary
from core.labs.models import ResourceLifecycleStatus, Station


def get_station_status_summary() -> dict[str, Any]:
    inventory = Station.objects.filter(deleted_at__isnull=True)
    return status_summary(inventory, field="lifecycle_status", choices=ResourceLifecycleStatus.choices)
