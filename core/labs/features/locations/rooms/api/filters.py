"""Room-specific extension of the shared resource contract.

``status`` filters the deprecated seven-value status (computed, RS3); new clients use the separate filters.
"""

from core.common.api.filtering import Filter, PositiveIDField
from core.labs.features.base.resource_filters import resource_filter_spec
from core.labs.features.locations.api.filters import location_state_filters
from core.labs.models.resource.location.room import RoomStatus

ROOM_FILTERS = resource_filter_spec(
    [
        *[
            Filter(f"{name}_id", PositiveIDField(), f"{name}_id", "reference", multiple=True)
            for name in ("country", "city", "building")
        ],
        *location_state_filters(),
    ],
    search_fields=("sku", "name", "label"),
    status_choices=RoomStatus.choices,
    status_lookup="legacy_status",
)
