"""Station-owned recorded lifecycle status aggregates."""

from typing import Any

from core.common.queries.status_summary import status_summary, with_latest_status
from core.labs.models.resource.location.station import Station, StationStatus, StationStatusRecord


def get_station_status_summary() -> dict[str, Any]:
    inventory = with_latest_status(
        Station.objects.filter(deleted_at__isnull=True),
        records=StationStatusRecord.objects.all(), resource_field="station_id",
    )
    return status_summary(inventory, field="summary_status", choices=StationStatus.choices)
