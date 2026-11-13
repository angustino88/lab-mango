"""Display-status history of one unit, rebuilt from the stored facts that make up ``display_status``.

``display_status`` is never stored (spec.md, priority table). Its history is replayed from the facts
that are: lifecycle and condition changes (``EquipmentEvent``), loans (``EquipmentLoan``) and bench
placements (``EquipmentAssignment``). Calibration is not replayed: it has no recorded change, so a unit
shown ``calibration_overdue`` today appears here with the label its other facts give.

The replay walks backward from the unit's current state over at most ``SOURCE_LIMIT`` newest rows per
source, so the read is bounded (4 queries). When a source is truncated, history stops at the oldest
point every source still covers and the creation row is omitted.

One command writes several facts a few milliseconds apart (leaving service resets the condition, a return
can set a new condition, marking a lost unit closes its loan). Facts recorded within ``STEP_WINDOW`` of
each other form one step, so the history never shows a label that only existed inside one command.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from core.labs.models import (
    Equipment,
    EquipmentCondition,
    EquipmentDisplayStatus,
    EquipmentEvent,
    EquipmentEventAxis,
    EquipmentLifecycleState,
    EquipmentLoan,
)
from core.labs.models.resource.equipment.assignment import EquipmentAssignment

from .state_history import state_label

SOURCE_LIMIT = 500
STEP_WINDOW = timedelta(seconds=2)

_LIFECYCLE = "lifecycle"
_CONDITION = "condition"
_LOAN = "loan"
_BENCH = "bench"


@dataclass(frozen=True, slots=True)
class DisplayStatusChange:
    """One change of ``display_status``; ``previous_display_status`` is ``None`` for the creation row."""

    display_status: str
    previous_display_status: str | None
    occurred_at: datetime
    actor: Any
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _State:
    lifecycle: str
    condition: str
    loan: bool
    bench: bool


@dataclass(frozen=True, slots=True)
class _Change:
    at: datetime
    fact: str
    before: str | bool
    actor: Any
    reason: str
    details: dict[str, Any]
    tiebreak: tuple[int, int]


def display_label(state: _State) -> str:
    """``display_status`` for a set of facts, in the priority order of spec.md (calibration excluded)."""
    if state.lifecycle != EquipmentLifecycleState.IN_SERVICE or state.condition != EquipmentCondition.OPERATIONAL:
        return state_label(state.lifecycle, state.condition)
    if state.loan:
        return str(EquipmentDisplayStatus.BORROWED)
    if state.bench:
        return str(EquipmentDisplayStatus.IN_USE)
    return str(EquipmentDisplayStatus.AVAILABLE)


def equipment_status_history(*, equipment_id: int) -> list[DisplayStatusChange]:
    """``display_status`` changes of one non-deleted unit, newest first.

    Raises ``Equipment.DoesNotExist`` for a missing or deleted unit. 4 queries.
    """
    unit = Equipment.objects.only("pk", "created", "lifecycle_state", "condition").get(
        pk=equipment_id, deleted_at__isnull=True
    )
    events = list(
        EquipmentEvent.objects.filter(equipment_id=equipment_id)
        .select_related("actor")
        .order_by("-occurred_at", "-id")[:SOURCE_LIMIT]
    )
    loans = list(
        EquipmentLoan.objects.filter(equipment_id=equipment_id)
        .select_related("batch__borrower", "handed_over_by", "received_by")
        .order_by("-handed_over_at", "-id")[:SOURCE_LIMIT]
    )
    benches = list(
        EquipmentAssignment.objects.filter(equipment_id=equipment_id)
        .select_related("bench", "creator", "last_modified_by")
        .order_by("-assigned_at", "-id")[:SOURCE_LIMIT]
    )

    cutoff = _cutoff(
        (events, lambda row: row.occurred_at),
        (loans, lambda row: row.handed_over_at),
        (benches, lambda row: row.assigned_at),
    )
    creation = next((event for event in events if not event.from_value), None)
    changes = [*_event_changes(events), *_loan_changes(loans), *_bench_changes(benches)]
    if cutoff is not None:
        changes = [change for change in changes if change.at > cutoff]
    changes.sort(key=lambda change: (change.at, change.tiebreak), reverse=True)

    state = _State(
        lifecycle=unit.lifecycle_state,
        condition=unit.condition,
        loan=any(loan.returned_at is None for loan in loans),
        bench=any(placement.unassigned_at is None for placement in benches),
    )
    history: list[DisplayStatusChange] = []
    for step in _steps(changes):
        after = state
        for change in step:
            state = _undo(state, change)
        before = state
        if display_label(after) != display_label(before):
            cause = _cause(step, after, before)
            history.append(
                DisplayStatusChange(
                    display_status=display_label(after),
                    previous_display_status=display_label(before),
                    occurred_at=cause.at,
                    actor=cause.actor,
                    reason=cause.reason,
                    details=cause.details,
                )
            )
    if cutoff is None:
        history.append(
            DisplayStatusChange(
                display_status=display_label(state),
                previous_display_status=None,
                occurred_at=unit.created,
                actor=creation.actor if creation is not None else None,
                reason=creation.reason if creation is not None else "",
            )
        )
    return history


def _cutoff(*sources) -> datetime | None:
    """The oldest time every source still covers, or ``None`` when no source was truncated."""
    times = [time_of(rows[-1]) for rows, time_of in sources if len(rows) >= SOURCE_LIMIT]
    return max(times) if times else None


def _event_changes(events: list[EquipmentEvent]) -> list[_Change]:
    return [
        _Change(
            at=event.occurred_at,
            fact=_LIFECYCLE if event.axis == EquipmentEventAxis.LIFECYCLE else _CONDITION,
            before=event.from_value,
            actor=event.actor,
            reason=event.reason,
            details=dict(event.details or {}),
            tiebreak=(0, event.pk),
        )
        for event in events
        if event.from_value  # the creation event is the creation row, not a change
    ]


def _loan_changes(loans: list[EquipmentLoan]) -> list[_Change]:
    changes = []
    for loan in loans:
        details = {"loan_id": loan.pk, "borrower_name": loan.batch.borrower_label}
        changes.append(
            _Change(
                at=loan.handed_over_at,
                fact=_LOAN,
                before=False,
                actor=loan.handed_over_by,
                reason=loan.batch.purpose,
                details={**details, "due_at": loan.due_at.isoformat()},
                tiebreak=(1, loan.pk),
            )
        )
        if loan.returned_at is not None:
            changes.append(
                _Change(
                    at=loan.returned_at,
                    fact=_LOAN,
                    before=True,
                    actor=loan.received_by,
                    reason=loan.condition_in,
                    details={**details, "close_reason": loan.close_reason},
                    tiebreak=(1, loan.pk),
                )
            )
    return changes


def _bench_changes(placements: list[EquipmentAssignment]) -> list[_Change]:
    changes = []
    for placement in placements:
        bench_name = placement.bench.name if placement.bench is not None else ""
        details = {"bench": {"id": placement.bench_id, "name": bench_name}}
        changes.append(
            _Change(
                at=placement.assigned_at,
                fact=_BENCH,
                before=False,
                actor=placement.creator,
                reason="",
                details=details,
                tiebreak=(2, placement.pk),
            )
        )
        if placement.unassigned_at is not None:
            changes.append(
                _Change(
                    at=placement.unassigned_at,
                    fact=_BENCH,
                    before=True,
                    actor=placement.last_modified_by,
                    reason="",
                    details=details,
                    tiebreak=(2, placement.pk),
                )
            )
    return changes


def _undo(state: _State, change: _Change) -> _State:
    """The state just before ``change``."""
    if change.fact == _LIFECYCLE:
        return replace(state, lifecycle=str(change.before))
    if change.fact == _CONDITION:
        return replace(state, condition=str(change.before))
    if change.fact == _LOAN:
        return replace(state, loan=bool(change.before))
    return replace(state, bench=bool(change.before))


def _steps(changes: list[_Change]) -> list[list[_Change]]:
    """Group newest-first changes that follow each other within ``STEP_WINDOW``."""
    steps: list[list[_Change]] = []
    for change in changes:
        if steps and steps[-1][-1].at - change.at <= STEP_WINDOW:
            steps[-1].append(change)
        else:
            steps.append([change])
    return steps


def _deciding_fact(state: _State) -> str | None:
    """The fact that decides the label, in priority order; ``None`` for ``available``."""
    if state.lifecycle != EquipmentLifecycleState.IN_SERVICE:
        return _LIFECYCLE
    if state.condition != EquipmentCondition.OPERATIONAL:
        return _CONDITION
    if state.loan:
        return _LOAN
    if state.bench:
        return _BENCH
    return None


def _cause(step: list[_Change], after: _State, before: _State) -> _Change:
    """The change that explains a step: the one behind the new label, else behind the old one."""
    for fact in (_deciding_fact(after), _deciding_fact(before)):
        for change in step:
            if change.fact == fact:
                return change
    return step[0]


__all__ = ("SOURCE_LIMIT", "DisplayStatusChange", "display_label", "equipment_status_history")
