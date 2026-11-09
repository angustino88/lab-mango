"""SLA engine: deadline computation, clock pause/resume, and live SLA state.

Clocks run on wall-clock minutes (no business-hours calendar yet). A status with ``pauses_sla=True``
(e.g. *Waiting for Customer*) freezes the clocks; on resume every pending deadline is pushed out by the paused
duration, so ``response_due_at`` / ``resolution_due_at`` always hold the *effective* deadline.
"""

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from core.support_desk.contracts import SlaState, SystemState
from core.support_desk.models.priority import SupportPriority
from core.support_desk.models.settings import SupportSettings
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.ticket import SupportTicket


def _add_minutes(start: datetime, minutes: int | None) -> datetime | None:
    return start + timedelta(minutes=minutes) if minutes else None


def compute_deadlines(
    priority: SupportPriority,
    *,
    start: datetime,
    paused_seconds: int = 0,
    enabled: bool | None = None,
) -> dict[str, datetime | None]:
    """Return ``{"response_due_at", "resolution_due_at"}`` for ``priority`` measured from ``start``."""
    if enabled is None:
        enabled = SupportSettings.get_solo().sla_enabled
    if not enabled:
        return {"response_due_at": None, "resolution_due_at": None}
    shift = timedelta(seconds=paused_seconds)
    response = _add_minutes(start, priority.response_target_minutes)
    resolution = _add_minutes(start, priority.resolution_target_minutes)
    return {
        "response_due_at": response + shift if response else None,
        "resolution_due_at": resolution + shift if resolution else None,
    }


def apply_status_sla_transition(
    ticket: SupportTicket,
    from_status: SupportStatus,
    to_status: SupportStatus,
    *,
    now: datetime,
) -> tuple[dict[str, Any], str | None]:
    """Compute ticket column updates needed when moving between statuses.

    Returns ``(updates, event)`` where ``event`` is ``"paused"``, ``"resumed"`` or ``None``.
    """
    updates: dict[str, Any] = {}
    if to_status.pauses_sla and not from_status.pauses_sla and ticket.sla_paused_at is None:
        updates["sla_paused_at"] = now
        return updates, "paused"

    if from_status.pauses_sla and not to_status.pauses_sla and ticket.sla_paused_at is not None:
        paused_for = max(now - ticket.sla_paused_at, timedelta(0))
        updates["sla_paused_at"] = None
        updates["sla_paused_seconds"] = ticket.sla_paused_seconds + int(paused_for.total_seconds())
        if ticket.response_due_at and ticket.first_response_at is None:
            updates["response_due_at"] = ticket.response_due_at + paused_for
        if ticket.resolution_due_at:
            updates["resolution_due_at"] = ticket.resolution_due_at + paused_for
        return updates, "resumed"
    return updates, None


def _window_state(
    *,
    started: datetime,
    due: datetime | None,
    done_at: datetime | None,
    breached_at: datetime | None,
    paused: bool,
    now: datetime,
    at_risk_percent: int,
) -> SlaState:
    if due is None:
        return SlaState.NONE
    if done_at is not None:
        return SlaState.BREACHED if (breached_at or done_at > due) else SlaState.MET
    if breached_at is not None or now > due:
        return SlaState.BREACHED
    if paused:
        return SlaState.PAUSED
    total = (due - started).total_seconds()
    elapsed = (now - started).total_seconds()
    if total > 0 and (elapsed / total) * 100 >= at_risk_percent:
        return SlaState.AT_RISK
    return SlaState.OK


def sla_summary(ticket: SupportTicket, *, now: datetime | None = None, at_risk_percent: int | None = None) -> dict[str, Any]:
    """Live SLA health of a ticket (pure read, safe for serializers)."""
    now = now or timezone.now()
    if at_risk_percent is None:
        at_risk_percent = SupportSettings.get_solo().sla_at_risk_percent
    paused = ticket.sla_paused_at is not None
    is_done = ticket.status.system_state == SystemState.DONE.value
    resolved_marker = ticket.resolved_at or (ticket.closed_at if is_done else None)

    response = _window_state(
        started=ticket.created_at,
        due=ticket.response_due_at,
        done_at=ticket.first_response_at,
        breached_at=ticket.response_breached_at,
        paused=paused,
        now=now,
        at_risk_percent=at_risk_percent,
    )
    resolution = _window_state(
        started=ticket.created_at,
        due=ticket.resolution_due_at,
        done_at=resolved_marker,
        breached_at=ticket.resolution_breached_at,
        paused=paused,
        now=now,
        at_risk_percent=at_risk_percent,
    )
    severity = [SlaState.BREACHED, SlaState.AT_RISK, SlaState.PAUSED, SlaState.OK, SlaState.MET, SlaState.NONE]
    overall = next((state for state in severity if state in (response, resolution)), SlaState.NONE)
    return {
        "state": overall.value,
        "response": {
            "state": response.value,
            "due_at": ticket.response_due_at,
            "breached_at": ticket.response_breached_at,
        },
        "resolution": {
            "state": resolution.value,
            "due_at": ticket.resolution_due_at,
            "breached_at": ticket.resolution_breached_at,
        },
        "paused": paused,
    }
