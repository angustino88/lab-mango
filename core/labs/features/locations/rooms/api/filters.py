"""Room-specific extension of the shared resource contract."""

from core.common.api.filtering import Filter, PositiveIDField
from core.labs.features.base.resource_filters import resource_filter_spec
from core.labs.features.locations.api.filters import location_state_filters

ROOM_FILTERS = resource_filter_spec(
    [
        *[
            Filter(f"{name}_id", PositiveIDField(), f"{name}_id", "reference", multiple=True)
            for name in ("country", "city", "building")
        ],
        *location_state_filters(),
    ],
    search_fields=("sku", "name", "label"),
)
