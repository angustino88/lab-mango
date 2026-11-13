"""Station aggregates over the deprecated seven-value ``status``, computed from the separate facts (RS3)."""

from typing import Any

from core.common.queries.status_summary import status_summary
from core.labs.models.resource.base.availability import with_location_state
from core.labs.models.resource.location.station import Station, StationStatus


def get_station_status_summary() -> dict[str, Any]:
    inventory = with_location_state(Station.objects.filter(deleted_at__isnull=True), "station")
    return status_summary(inventory, field="legacy_status", choices=StationStatus.choices)
