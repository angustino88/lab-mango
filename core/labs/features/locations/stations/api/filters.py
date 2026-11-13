"""Station collection filter contract; ORM mappings never come from the client.

``status`` filters the deprecated seven-value status (computed, RS3); new clients use the separate filters.
"""

from core.common.api.filtering import Filter, PositiveIDField
from core.labs.features.base.resource_filters import resource_filter_spec
from core.labs.features.locations.api.filters import location_state_filters
from core.labs.models.resource.location.station import StationStatus

STATION_FILTERS = resource_filter_spec(
    [
        Filter("room_id", PositiveIDField(), "room_id", "reference", multiple=True, label="Room"),
        Filter("type_id", PositiveIDField(), "type_id", "reference", multiple=True, label="Station type"),
        *location_state_filters(),
    ],
    search_fields=("sku", "name", "label"),
    status_choices=StationStatus.choices,
    status_lookup="legacy_status",
)
