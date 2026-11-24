"""Update mode (``upsert``): compare a row with the stored record and keep only what changes.

Rules shared by every sheet that updates records:
- the asset tag is the key and never changes;
- a blank cell keeps the stored value (a workbook cannot clear a field);
- a row whose values all match the record is reported as ``existing`` (unchanged) and writes nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

from core.labs.models.resource.base.downtime import ResourceDowntime

from .context import ImportRun, Row


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def same_value(stored: Any, new: Any) -> bool:
    """Equality that ignores representation: 2 == 2.0 == Decimal("2.00"), " a " == "a", lists by item."""
    left, right = _number(stored), _number(new)
    if left is not None and right is not None:
        return left == right
    if isinstance(stored, str) and isinstance(new, str):
        return stored.strip() == new.strip()
    if isinstance(stored, list | tuple) and isinstance(new, list | tuple):
        return len(stored) == len(new) and all(same_value(a, b) for a, b in zip(stored, new, strict=True))
    if isinstance(stored, dict) and isinstance(new, dict):
        return stored.keys() == new.keys() and all(same_value(stored[key], new[key]) for key in stored)
    return stored == new


def changed_fields(instance: Any, data: dict[str, Any]) -> dict[str, Any]:
    """The entries of ``data`` that differ from ``instance``; ``sku`` is never part of an update."""
    return {
        key: value
        for key, value in data.items()
        if key != "sku" and not same_value(getattr(instance, key, None), value)
    }


def current_condition(resource: Any) -> str:
    return ResourceDowntime.objects.condition_of(resource)


def apply_space_state(
    run: ImportRun,
    row: Row,
    resource: Any,
    *,
    lifecycle: str | None,
    access: str | None,
    condition: str | None,
    change_lifecycle: Callable[..., Any],
    open_downtime: Callable[[str | None], None],
) -> bool:
    """Change access, condition and lifecycle where the row differs from ``resource``; ``True`` if any did.

    A condition is opened as a downtime from now (as on create). Ending or changing a downtime that is already
    open is a decision about the running window, so it is reported as a warning and left to the app.
    """
    changed = False
    metadata = {"source": "workbook_import"}
    access_policy = getattr(resource, "access_policy", None)
    if access is not None and access_policy is not None and access != access_policy:
        change_lifecycle(access_policy=access, metadata=metadata)
        changed = True
    if condition is not None:
        stored = current_condition(resource)
        if condition != stored:
            if stored == "operational":
                open_downtime(condition)
                changed = True
            else:
                run.row_warning(
                    row,
                    f"Condition is {stored.replace('_', ' ')} (an open downtime); end or change it in the app. "
                    "Not changed by the import.",
                    key="condition",
                    code="condition_not_changed",
                )
    if lifecycle is not None and lifecycle != resource.lifecycle_status:
        change_lifecycle(lifecycle_status=lifecycle, metadata=metadata)
        changed = True
    return changed


__all__ = ["apply_space_state", "changed_fields", "current_condition", "same_value"]
