"""Station policies and write commands."""

from core.labs.features.base.resource_image_commands import ResourceImageCommands
from core.labs.models import Station

from .services import (
    change_station_lifecycle,
    create_station,
    create_station_slot,
    create_station_type,
    delete_station,
    delete_station_slot,
    delete_station_type,
    place_station,
    record_station_status,
    update_station,
    update_station_slot,
    update_station_type,
)

# Image use cases (replace/remove) for this resource; see core/labs/features/base/resource_image_commands.py.
station_images = ResourceImageCommands(Station)


__all__ = [
    "station_images",
    "change_station_lifecycle", "create_station", "create_station_slot", "create_station_type", "delete_station",
    "delete_station_slot", "delete_station_type", "place_station", "record_station_status",
    "update_station", "update_station_slot", "update_station_type",
]
