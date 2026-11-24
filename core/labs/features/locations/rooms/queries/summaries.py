"""Lifecycle counts for live rooms."""

from typing import Any

from core.common.queries.status_summary import status_summary
from core.labs.models import ResourceLifecycleStatus, Room


def get_room_status_summary() -> dict[str, Any]:
    inventory = Room.objects.filter(deleted_at__isnull=True)
    return status_summary(inventory, field="lifecycle_status", choices=ResourceLifecycleStatus.choices)
