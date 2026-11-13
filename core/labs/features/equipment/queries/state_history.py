"""Replay of lifecycle and condition history, for other features' time-based reports.

Lifecycle changes are ``EquipmentEvent`` rows; condition changes are the start and end of each
``ResourceDowntime`` window (RS2): ``condition`` from ``starts_at``, ``operational`` from ``ends_at``.
"""

from collections import defaultdict
from datetime import datetime
from typing import Any

from core.labs.models import (
    Equipment,
    EquipmentCondition,
    EquipmentDisplayStatus,
    EquipmentEvent,
    EquipmentEventAxis,
    EquipmentLifecycleState,
    ResourceDowntime,
)

_CONDITION_AXIS = "condition"

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
    Three queries: units, their lifecycle events, their downtime windows.
    """
    units = list(
        Equipment.objects.filter(deleted_at__isnull=True, created__lt=until)
        .order_by("pk")
        .values("pk", "name", "created", "lifecycle_state")
    )
    unit_ids = [unit["pk"] for unit in units]
    events: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in (
        EquipmentEvent.objects.filter(equipment_id__in=unit_ids)
        .order_by("equipment_id", "occurred_at", "id")
        .values("equipment_id", "axis", "from_value", "to_value", "occurred_at")
    ):
        events[row["equipment_id"]].append(dict(row))
    for window in (
        ResourceDowntime.objects.for_resources(Equipment, unit_ids)
        .not_cancelled()
        .filter(starts_at__lt=until)
        .values("resource_object_id", "condition", "starts_at", "ends_at")
    ):
        unit_events = events[int(window["resource_object_id"])]
        unit_events.append(
            {
                "axis": _CONDITION_AXIS,
                "from_value": "",
                "to_value": window["condition"],
                "occurred_at": window["starts_at"],
            }
        )
        if window["ends_at"] is not None:
            unit_events.append(
                {
                    "axis": _CONDITION_AXIS,
                    "from_value": window["condition"],
                    "to_value": EquipmentCondition.OPERATIONAL,
                    "occurred_at": window["ends_at"],
                }
            )

    result = {}
    for unit in units:
        # A window's end sorts before the next window's start at the same moment.
        history = sorted(
            events[unit["pk"]],
            key=lambda event: (event["occurred_at"], event["to_value"] != EquipmentCondition.OPERATIONAL),
        )
        state: dict[str, str] = {
            EquipmentEventAxis.LIFECYCLE: _initial(history, EquipmentEventAxis.LIFECYCLE, unit["lifecycle_state"]),
            _CONDITION_AXIS: EquipmentCondition.OPERATIONAL,
        }
        timeline = [(unit["created"], state_label(state["lifecycle"], state[_CONDITION_AXIS]))]
        for event in history:
            if event["occurred_at"] >= until:
                break
            state[event["axis"]] = event["to_value"]
            label = state_label(state["lifecycle"], state[_CONDITION_AXIS])
            if label != timeline[-1][1]:
                timeline.append((max(event["occurred_at"], unit["created"]), label))
        result[unit["pk"]] = {"name": unit["name"], "timeline": timeline}
    return result


def _initial(history: list[dict], axis: str, current: str) -> str:
    for event in history:
        if event["axis"] == axis:
            return event["from_value"] or event["to_value"]
    return current


__all__ = ("equipment_state_timelines", "state_label")
