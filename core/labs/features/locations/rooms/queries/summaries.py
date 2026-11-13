"""Room lifecycle status aggregates over the stored ``status`` column."""

from typing import Any

from core.common.queries.status_summary import status_summary
from core.labs.models.resource.location.room import Room, RoomStatus


def get_room_status_summary() -> dict[str, Any]:
    inventory = Room.objects.filter(deleted_at__isnull=True)
    return status_summary(inventory, field="status", choices=RoomStatus.choices)
