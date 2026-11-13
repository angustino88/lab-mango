"""Room policies and write commands."""

from core.labs.features.base.resource_image_commands import ResourceImageCommands
from core.labs.models import Room

from .services import (
    change_room_lifecycle,
    create_room,
    delete_room,
    generate_room_slots,
    record_room_observation,
    record_room_status,
    update_room,
)

# Image use cases (replace/remove) for this resource; see core/labs/features/base/resource_image_commands.py.
room_images = ResourceImageCommands(Room)


__all__ = [
    "room_images",
    "change_room_lifecycle", "create_room", "delete_room", "generate_room_slots", "record_room_observation",
    "record_room_status", "update_room",
]
