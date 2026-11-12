"""Shared collection contract for ResourceModel descendants, not model methods.

Only inherited identity/ownership/timestamp fields belong here. Concrete resource
features supply their own status choices, annotation paths and extra filters.
"""

from collections.abc import Sequence
from typing import Any

from rest_framework import serializers

from core.common.api.filtering import Filter, FilterSpec, PositiveIDField, QueryDateTimeField


def resource_filter_spec(
    filters: Sequence[Filter] = (),
    *,
    search_fields: Sequence[str] = ("sku", "name"),
    status_choices: Any = None,
    status_lookup: str = "current_status",
    distinct: bool = False,
) -> FilterSpec:
    """Specialize the general FilterSpec with ResourceModel's shared fields.

    Concrete features append explicit filters and supply their own status enum.
    Non-resource collections use FilterSpec directly, not this factory.
    """
    common = [
        Filter("id", PositiveIDField(), "pk", "reference", multiple=True),
        Filter("owner_id", PositiveIDField(), "owner_id", "reference", multiple=True),
        Filter("team_id", PositiveIDField(), "team_id", "reference", multiple=True),
        Filter("created_at_after", QueryDateTimeField(required=False), "created__gte", "datetime"),
        Filter("created_at_before", QueryDateTimeField(required=False), "created__lt", "datetime"),
    ]
    if status_choices is not None:
        common.append(
            Filter("status", serializers.ChoiceField(choices=status_choices), status_lookup, "enum", multiple=True)
        )
    return FilterSpec(
        [*common, *filters],
        search_fields=search_fields,
        ordering={"sku": "sku", "name": "name", "created_at": "created", "id": "pk"},
        ranges=(("created_at_after", "created_at_before"),),
        search_alias=True,
        search_distinct=distinct,
    )
