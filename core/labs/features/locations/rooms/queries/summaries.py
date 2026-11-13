"""Room aggregates over the deprecated seven-value ``status``, computed from the separate facts (RS3)."""

from typing import Any

from core.common.queries.status_summary import status_summary
from core.labs.models.resource.base.availability import with_location_state
from core.labs.models.resource.location.room import Room, RoomStatus


def get_room_status_summary() -> dict[str, Any]:
    inventory = with_location_state(Room.objects.filter(deleted_at__isnull=True), "room")
    return status_summary(inventory, field="legacy_status", choices=RoomStatus.choices)
