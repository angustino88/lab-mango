"""Resource identifiers that cannot change after creation (SKU), enforced by the update commands."""

from collections.abc import Iterable
from typing import Any

from core.common.domain.errors import Conflict

IMMUTABLE_RESOURCE_FIELDS = ("sku",)


class ResourceFieldImmutable(Conflict):
    """Raised when an update tries to change a resource identifier such as the SKU."""

    code = "resource_field_immutable"
    default_message = "A resource identifier cannot be changed."


def _normalized(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def drop_unchanged_immutable_fields(
    instance: Any, data: dict[str, Any], fields: Iterable[str] = IMMUTABLE_RESOURCE_FIELDS
) -> dict[str, Any]:
    """Return ``data`` without immutable fields that repeat the stored value; reject a changed one.

    Forms send the whole record back, SKU included, so an unchanged SKU is accepted and ignored.
    Call it on the row the command already holds ``select_for_update`` on, so the comparison is not racy.
    """
    data = dict(data)
    for field in fields:
        if field not in data:
            continue
        if _normalized(data[field]) != _normalized(getattr(instance, field)):
            raise ResourceFieldImmutable(f"{field} cannot be changed after resource creation.")
        del data[field]
    return data


__all__ = ["IMMUTABLE_RESOURCE_FIELDS", "ResourceFieldImmutable", "drop_unchanged_immutable_fields"]
