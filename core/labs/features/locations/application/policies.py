"""Pure capacity and utility policies for station placement."""

from collections.abc import Mapping

from django.core.exceptions import ValidationError


def check_limit(field, capacity, requested):
    if capacity is not None and requested is not None and requested > capacity:
        raise ValidationError({field: "Existing allocation or requested capacity exceeds this limit."})


def validate_utilities(required, provided, *, field="utilities"):
    if not isinstance(required, Mapping) or not isinstance(provided, Mapping):
        raise ValidationError({field: "Utilities must be an object."})
    for key, requirement in required.items():
        if requirement is None or requirement is False:
            continue
        available = provided.get(key)
        if isinstance(requirement, bool):
            satisfied = bool(available)
        elif isinstance(requirement, (int, float)):
            satisfied = isinstance(available, (int, float)) and available >= requirement
        else:
            satisfied = available == requirement
        if not satisfied:
            raise ValidationError({field: f"Required utility is not supported: {key}."})


__all__ = ["check_limit", "validate_utilities"]
