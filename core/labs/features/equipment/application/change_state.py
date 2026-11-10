"""Change an equipment unit's lifecycle state or condition (redesign step 2).

Race guard: the ``Equipment`` row lock, then placement rows, then equipment booking rows (the
feature lock order). Database guards: ``equipment_lifecycle_valid``, ``equipment_condition_valid``,
``equipment_condition_only_in_service``. Idempotency: the target state already current returns the
unit unchanged and writes no event.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.labs.features.equipment.exceptions import EquipmentAlreadyPlaced, EquipmentOnLoan, InvalidEquipmentStatus
from core.labs.models import (
    BookingStatus,
    Equipment,
    EquipmentBooking,
    EquipmentCondition,
    EquipmentEvent,
    EquipmentEventAxis,
    EquipmentLifecycleState,
    ensure_booking_status_transition,
)
from core.labs.models.resource.equipment.equipment import GONE_LIFECYCLE_STATES, LIFECYCLE_TRANSITIONS

from ._placement import close_loan_as_lost, close_placement, lock_active_loan, lock_active_placement

REASON_MAX_LENGTH = 500
ORGANISATION_MAX_LENGTH = 255


@dataclass(frozen=True, slots=True)
class ChangeConditionInput:
    equipment_id: int
    condition: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ChangeLifecycleInput:
    equipment_id: int
    lifecycle_state: str
    reason: str = ""
    receiving_organisation: str = ""
    transfer_date: date | None = None


@transaction.atomic
def change_condition(command: ChangeConditionInput, *, actor) -> Equipment:
    """Set whether an in-service unit works. Never opens or closes a placement (AC4)."""
    if command.condition not in EquipmentCondition.values:
        raise ValidationError({"condition": "Select a valid condition."})
    reason = _clean(command.reason, field="reason", limit=REASON_MAX_LENGTH)
    equipment = _lock(command.equipment_id)
    if equipment.condition == command.condition:
        return equipment
    if equipment.lifecycle_state != EquipmentLifecycleState.IN_SERVICE:
        raise InvalidEquipmentStatus("The condition can change only while the equipment is in service.")
    _record(equipment, EquipmentEventAxis.CONDITION, command.condition, reason=reason, details={}, actor=actor)
    return equipment


@transaction.atomic
def change_lifecycle(command: ChangeLifecycleInput, *, actor) -> Equipment:
    """Move a unit along ``LIFECYCLE_TRANSITIONS``.

    Entering ``transferred_out``, ``retired`` or ``lost`` refuses a unit on a bench, closes any
    other placement, and cancels its reserved equipment bookings. Leaving ``in_service`` resets the
    condition to ``operational`` (its own event). Marking a unit lost is always this manual command.
    """
    target = command.lifecycle_state
    if target not in EquipmentLifecycleState.values:
        raise ValidationError({"lifecycle_state": "Select a valid lifecycle state."})
    reason = _clean(command.reason, field="reason", limit=REASON_MAX_LENGTH)
    equipment = _lock(command.equipment_id)
    current = equipment.lifecycle_state
    if current == target:
        return equipment
    if target not in LIFECYCLE_TRANSITIONS[current]:
        raise InvalidEquipmentStatus(f"The lifecycle state cannot change from {current} to {target}.")
    details: dict[str, Any] = {}
    if target == EquipmentLifecycleState.TRANSFERRED_OUT:
        organisation = _clean(
            command.receiving_organisation, field="receiving_organisation", limit=ORGANISATION_MAX_LENGTH
        )
        if not organisation:
            raise ValidationError({"receiving_organisation": "Name the organisation that receives the equipment."})
        details = {
            "receiving_organisation": organisation,
            "transfer_date": (command.transfer_date or timezone.localdate()).isoformat(),
        }
    if target in GONE_LIFECYCLE_STATES:
        if target == EquipmentLifecycleState.LOST:
            lost_loan = close_loan_as_lost(equipment, actor=actor)
            if lost_loan is not None:
                details["closed_loan_id"] = lost_loan.pk
        elif lock_active_loan(equipment) is not None:
            raise EquipmentOnLoan("Take the equipment back before changing its lifecycle state.")
        placement = lock_active_placement(equipment)
        if placement is not None and placement.bench_id is not None:
            raise EquipmentAlreadyPlaced("Remove the equipment from its bench before changing its lifecycle state.")
        if placement is not None:
            close_placement(placement, actor=actor)
        cancelled = _cancel_reserved_bookings(equipment, reason=reason or f"Equipment is {target}.")
        if cancelled:
            details["cancelled_booking_ids"] = cancelled
    if target != EquipmentLifecycleState.IN_SERVICE and equipment.condition != EquipmentCondition.OPERATIONAL:
        _record(
            equipment,
            EquipmentEventAxis.CONDITION,
            EquipmentCondition.OPERATIONAL,
            reason="Reset because the equipment left service.",
            details={},
            actor=actor,
        )
    _record(equipment, EquipmentEventAxis.LIFECYCLE, target, reason=reason, details=details, actor=actor)
    return equipment


def record_initial_lifecycle(equipment: Equipment, *, actor) -> None:
    """History starts with the state a unit was created in (``from_value`` empty)."""
    EquipmentEvent.objects.create(
        equipment=equipment,
        axis=EquipmentEventAxis.LIFECYCLE,
        from_value="",
        to_value=equipment.lifecycle_state,
        reason="Created.",
        actor=_user(actor),
    )


def _lock(equipment_id: int) -> Equipment:
    return Equipment.objects.select_for_update().get(pk=equipment_id, deleted_at__isnull=True)


def _clean(value: str, *, field: str, limit: int) -> str:
    text = (value or "").strip()
    if len(text) > limit:
        raise ValidationError({field: f"Use at most {limit} characters."})
    return text


def _record(equipment: Equipment, axis: str, value: str, *, reason: str, details: dict, actor) -> None:
    field = "lifecycle_state" if axis == EquipmentEventAxis.LIFECYCLE else "condition"
    previous = getattr(equipment, field)
    now = timezone.now()
    Equipment.objects.filter(pk=equipment.pk).update(
        **{field: value}, modified=now, last_modified_by=_user(actor) or equipment.last_modified_by
    )
    setattr(equipment, field, value)
    EquipmentEvent.objects.create(
        equipment=equipment,
        axis=axis,
        from_value=previous,
        to_value=value,
        reason=reason,
        details=details,
        actor=_user(actor),
        occurred_at=now,
    )


def _cancel_reserved_bookings(equipment: Equipment, *, reason: str) -> list[int]:
    bookings = list(
        EquipmentBooking.objects.select_for_update()
        .filter(equipment=equipment, status=BookingStatus.RESERVED)
        .order_by("pk")
    )
    for booking in bookings:
        ensure_booking_status_transition(current_status=booking.status, target_status=BookingStatus.CANCELLED)
        booking.status = BookingStatus.CANCELLED
        booking.cancellation_reason = reason
        booking.save(update_fields=("status", "cancellation_reason", "modified"))
    return [booking.pk for booking in bookings]


def _user(actor):
    return actor if getattr(actor, "is_authenticated", False) else None


__all__ = (
    "ChangeConditionInput",
    "ChangeLifecycleInput",
    "change_condition",
    "change_lifecycle",
    "record_initial_lifecycle",
)
