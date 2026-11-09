"""Room-owned recorded lifecycle status aggregates."""

from typing import Any

from core.common.queries.status_summary import status_summary, with_latest_status
from core.labs.models.resource.location.room import Room, RoomStatus, RoomStatusRecord


def get_room_status_summary() -> dict[str, Any]:
    inventory = with_latest_status(
        Room.objects.filter(deleted_at__isnull=True),
        records=RoomStatusRecord.objects.all(), resource_field="room_id",
    )
    return status_summary(inventory, field="summary_status", choices=RoomStatus.choices)
