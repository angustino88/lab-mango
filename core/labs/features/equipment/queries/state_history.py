"""Lifecycle and condition history: one unit's recorded events, and a replay for time-based reports."""

from collections import defaultdict
from datetime import datetime
from typing import Any

from django.db.models import QuerySet

from core.labs.models import (
    Equipment,
    EquipmentCondition,
    EquipmentDisplayStatus,
    EquipmentEvent,
    EquipmentEventAxis,
    EquipmentLifecycleState,
)

_LIFECYCLE_LABELS: dict[str, str] = {
    EquipmentLifecycleState.PLANNED: EquipmentDisplayStatus.ON_ORDER,
    EquipmentLifecycleState.TRANSFERRED_OUT: EquipmentDisplayStatus.TRANSFERRED,
    EquipmentLifecycleState.RETIRED: EquipmentDisplayStatus.RETIRED,
    EquipmentLifecycleState.LOST: EquipmentDisplayStatus.LOST,
}
_CONDITION_LABELS: dict[str, str] = {
    EquipmentCondition.IN_MAINTENANCE: EquipmentDisplayStatus.MAINTENANCE,
    EquipmentCondition.OUT_OF_SERVICE: EquipmentDisplayStatus.BROKEN,
}


def state_label(lifecycle_state: str, condition: str) -> str:
    """The display label for a lifecycle and condition pair, ignoring placement and calibration."""
    if lifecycle_state in _LIFECYCLE_LABELS:
        return _LIFECYCLE_LABELS[lifecycle_state]
    return _CONDITION_LABELS.get(condition, str(EquipmentDisplayStatus.AVAILABLE))


def equipment_state_timelines(*, until: datetime) -> dict[int, dict]:
    """Per non-deleted unit created before ``until``: ``{"name", "timeline": [(time, label), ...]}``.

    The timeline starts at the unit's creation and lists every label change before ``until``.
    Two queries: units, then their events.
    """
    units = list(
        Equipment.objects.filter(deleted_at__isnull=True, created__lt=until)
        .order_by("pk")
        .values("pk", "name", "created", "lifecycle_state", "condition")
    )
    events: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in (
        EquipmentEvent.objects.filter(equipment_id__in=[unit["pk"] for unit in units])
        .order_by("equipment_id", "occurred_at", "id")
        .values("equipment_id", "axis", "from_value", "to_value", "occurred_at")
    ):
        events[row["equipment_id"]].append(dict(row))

    result = {}
    for unit in units:
        history = events[unit["pk"]]
        state: dict[str, str] = {
            EquipmentEventAxis.LIFECYCLE: _initial(history, EquipmentEventAxis.LIFECYCLE, unit["lifecycle_state"]),
            EquipmentEventAxis.CONDITION: _initial(history, EquipmentEventAxis.CONDITION, unit["condition"]),
        }
        timeline = [(unit["created"], state_label(state["lifecycle"], state["condition"]))]
        for event in history:
            if event["occurred_at"] >= until:
                break
            state[event["axis"]] = event["to_value"]
            label = state_label(state["lifecycle"], state["condition"])
            if label != timeline[-1][1]:
                timeline.append((max(event["occurred_at"], unit["created"]), label))
        result[unit["pk"]] = {"name": unit["name"], "timeline": timeline}
    return result


def list_equipment_status_events(*, equipment_id: int) -> QuerySet[EquipmentEvent]:
    """Recorded lifecycle and condition changes of one non-deleted unit, newest first.

    Raises ``Equipment.DoesNotExist`` for a missing or deleted unit. 1 query, then page + count = 2 queries.
    """
    Equipment.objects.only("pk").get(pk=equipment_id, deleted_at__isnull=True)
    return (
        EquipmentEvent.objects.filter(equipment_id=equipment_id)
        .select_related("actor")
        .order_by("-occurred_at", "-id")
    )


def _initial(history: list[dict], axis: str, current: str) -> str:
    for event in history:
        if event["axis"] == axis:
            return event["from_value"] or event["to_value"]
    return current


__all__ = ("equipment_state_timelines", "list_equipment_status_events", "state_label")
