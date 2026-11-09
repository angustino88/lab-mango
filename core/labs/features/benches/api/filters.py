"""Bench extension: lifecycle status and actor-scoped favorites stay distinct."""

from core.common.api.filtering import Filter, PositiveIDField, StrictBooleanField
from core.labs.features.base.resource_filters import resource_filter_spec
from core.labs.models.resource.bench.bench import Bench

BENCH_FILTERS = resource_filter_spec(
    [
        Filter("setup_location_id", PositiveIDField(), "setup_location_id", "reference", multiple=True),
        Filter("bench_group_id", PositiveIDField(), "bench_group_id", "reference", multiple=True),
        Filter("type_id", PositiveIDField(), "type_id", "reference", multiple=True),
        Filter("favorite", StrictBooleanField(required=False), "is_favorite", "boolean"),
    ],
    search_fields=("sku", "name", "description"),
    status_choices=Bench.LIFECYCLE_STATUSES,
    status_lookup="lifecycle_status",
)
