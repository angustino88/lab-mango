"""Hand equipment over to a person, take it back, or extend the loan (redesign step 3).

Race guard: the ``Equipment`` row lock, then the booking row (when given), then placement and loan
rows; ``one_active_loan_per_equipment`` backs it in PostgreSQL. Idempotency: a hand-over for a
booking that already has its active loan returns that loan; a repeated return returns the loan it
closed; extending to the current due time changes nothing.
"""

from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.equipment.exceptions import (
    EquipmentNotAvailable,
    EquipmentNotOnLoan,
    EquipmentOnLoan,
    LoanManagedByBooking,
)
from core.labs.models import (
    Equipment,
    EquipmentBooking,
    EquipmentCondition,
    EquipmentLifecycleState,
    EquipmentLoan,
    LoanCloseReason,
)
from core.labs.models.resource.equipment.loan import CONDITION_NOTE_MAX_LENGTH

from ._placement import close_resting_placement, lock_active_loan, lock_active_placement
from .change_state import ChangeConditionInput, change_condition
from .place_equipment import PlaceEquipmentInput, place_equipment


@dataclass(frozen=True, slots=True)
class HandOverEquipmentInput:
    equipment_id: int
    borrower_id: int
    due_at: datetime
    condition_out: str = ""
    booking_id: int | None = None


@dataclass(frozen=True, slots=True)
class ReturnEquipmentInput:
    equipment_id: int
    condition_in: str = ""
    condition: str | None = None
    bench_id: int | None = None
    station_id: int | None = None
    room_id: int | None = None
    location_note: str = ""


@dataclass(frozen=True, slots=True)
class ExtendLoanInput:
    equipment_id: int
    due_at: datetime


@transaction.atomic
def hand_over_equipment(command: HandOverEquipmentInput, *, actor) -> EquipmentLoan:
    """Open a loan: the unit leaves its resting place and is with ``borrower`` until ``due_at``.

    The unit must be available: in service, operational, not on a bench, not on loan, and
    calibrated when it requires calibration.
    """
    now = timezone.now()
    if command.due_at <= now:
        raise ValidationError({"due_at": "The due time must be in the future."})
    condition_out = _note(command.condition_out, "condition_out")
    equipment = Equipment.objects.select_for_update().get(pk=command.equipment_id, deleted_at__isnull=True)
    borrower = get_user_model().objects.filter(pk=command.borrower_id, is_active=True).first()
    if borrower is None:
        raise ValidationError({"borrower_id": "Select an active user."})
    booking = None
    if command.booking_id is not None:
        booking = EquipmentBooking.objects.select_for_update().filter(pk=command.booking_id).first()
        if booking is None or booking.equipment_id != equipment.pk:
            raise ValidationError({"booking_id": "Select a booking of this equipment."})
    current = lock_active_loan(equipment)
    if current is not None:
        if booking is not None and current.booking_id == booking.pk:
            return current
        raise EquipmentOnLoan()
    reasons = _unavailable_reasons(equipment)
    if reasons:
        raise EquipmentNotAvailable(details={"reasons": reasons})
    close_resting_placement(equipment, actor=actor)
    try:
        with transaction.atomic():
            return EquipmentLoan.objects.create(
                equipment=equipment,
                borrower=borrower,
                booking=booking,
                handed_over_at=now,
                handed_over_by=_user(actor),
                due_at=command.due_at,
                condition_out=condition_out,
            )
    except IntegrityError as error:
        constraint = getattr(getattr(error.__cause__, "diag", None), "constraint_name", None)
        if constraint in {"one_active_loan_per_equipment", "labs_equipmentloan_booking_id_key"}:
            raise EquipmentOnLoan() from error
        raise


@transaction.atomic
def return_equipment(command: ReturnEquipmentInput, *, actor) -> EquipmentLoan:
    """Close the active loan, then optionally record the unit's condition and where it now is."""
    condition_in = _note(command.condition_in, "condition_in")
    if command.condition is not None and command.condition not in EquipmentCondition.values:
        raise ValidationError({"condition": "Select a valid condition."})
    equipment = Equipment.objects.select_for_update().get(pk=command.equipment_id, deleted_at__isnull=True)
    loan = lock_active_loan(equipment)
    if loan is None:
        latest = (
            EquipmentLoan.objects.filter(equipment=equipment, returned_at__isnull=False)
            .order_by("-returned_at", "-id")
            .first()
        )
        if latest is not None and latest.close_reason == LoanCloseReason.RETURNED:
            return latest
        raise EquipmentNotOnLoan()
    loan.returned_at = timezone.now()
    loan.received_by = _user(actor)
    loan.condition_in = condition_in
    loan.close_reason = LoanCloseReason.RETURNED
    loan.save(update_fields=("returned_at", "received_by", "condition_in", "close_reason", "modified"))
    if command.condition is not None:
        change_condition(
            ChangeConditionInput(equipment_id=equipment.pk, condition=command.condition, reason="Recorded at return."),
            actor=actor,
        )
    if (
        command.bench_id is not None
        or command.station_id is not None
        or command.room_id is not None
        or command.location_note
    ):
        place_equipment(
            PlaceEquipmentInput(
                equipment_id=equipment.pk,
                bench_id=command.bench_id,
                station_id=command.station_id,
                room_id=command.room_id,
                location_note=command.location_note,
            ),
            actor=actor,
        )
    return loan


@transaction.atomic
def extend_loan(command: ExtendLoanInput, *, actor) -> EquipmentLoan:
    """Move the due time of a loan that is not tied to a booking."""
    equipment = Equipment.objects.select_for_update().get(pk=command.equipment_id, deleted_at__isnull=True)
    loan = lock_active_loan(equipment)
    if loan is None:
        raise EquipmentNotOnLoan()
    if loan.booking_id is not None:
        raise LoanManagedByBooking()
    if loan.due_at == command.due_at:
        return loan
    if command.due_at <= timezone.now() or command.due_at <= loan.handed_over_at:
        raise ValidationError({"due_at": "The due time must be in the future."})
    loan.due_at = command.due_at
    loan.save(update_fields=("due_at", "modified"))
    return loan


def _unavailable_reasons(equipment: Equipment) -> list[str]:
    reasons = []
    if equipment.lifecycle_state != EquipmentLifecycleState.IN_SERVICE:
        reasons.append(f"lifecycle_state is {equipment.lifecycle_state}")
    if equipment.condition != EquipmentCondition.OPERATIONAL:
        reasons.append(f"condition is {equipment.condition}")
    placement = lock_active_placement(equipment)
    if placement is not None and placement.bench_id is not None:
        reasons.append("placed on a bench")
    if equipment.calibration_overdue:
        reasons.append("calibration overdue")
    return reasons


def _note(value: str, field: str) -> str:
    text = (value or "").strip()
    if len(text) > CONDITION_NOTE_MAX_LENGTH:
        raise ValidationError({field: f"Use at most {CONDITION_NOTE_MAX_LENGTH} characters."})
    return text


def _user(actor):
    return actor if getattr(actor, "is_authenticated", False) else None


__all__ = (
    "ExtendLoanInput",
    "HandOverEquipmentInput",
    "ReturnEquipmentInput",
    "extend_loan",
    "hand_over_equipment",
    "return_equipment",
)
