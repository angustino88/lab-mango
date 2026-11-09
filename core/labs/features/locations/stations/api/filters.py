"""Station collection filter contract; ORM mappings never come from the client."""

from core.common.api.filtering import Filter, PositiveIDField
from core.labs.features.base.resource_filters import resource_filter_spec
from core.labs.models.resource.location.station import StationStatus

STATION_FILTERS = resource_filter_spec(
    [
        Filter("room_id", PositiveIDField(), "room_id", "reference", multiple=True, label="Room"),
        Filter("type_id", PositiveIDField(), "type_id", "reference", multiple=True, label="Station type"),
    ],
    search_fields=("sku", "name", "label"),
    status_choices=StationStatus.choices,
)
