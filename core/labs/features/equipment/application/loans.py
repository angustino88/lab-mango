"""Hand equipment over to a person, take it back, or extend the loan; one item or several.

A loan batch is the slip: one borrower (a user or, without an account, a name) and purpose for
one or more items. Each item is its own loan line, so items can come back at different times.

Race guard: all ``Equipment`` rows locked in one query ordered by pk, then the booking row (when
given), then placement and loan rows; ``one_active_loan_per_equipment`` backs it in PostgreSQL.
Batch commands are all-or-nothing. Idempotency: a batch hand-over replays by ``idempotency_key``;
a hand-over for a booking that already has its loan returns it; a repeated return returns the
loan it closed; extending to the current due time changes nothing.
"""

import hashlib
import json
from collections.abc import Sequence
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
    LoanIdempotencyKeyReuse,
    ReservationConflict,
)
from core.labs.models import (
    Booking,
    BookingStatus,
    Equipment,
    EquipmentBooking,
    EquipmentCondition,
    EquipmentLifecycleState,
    EquipmentLoan,
    EquipmentLoanBatch,
    LoanCloseReason,
    ensure_booking_status_transition,
)
from core.labs.models.resource.equipment.loan import (
    BORROWER_NAME_MAX_LENGTH,
    CONDITION_NOTE_MAX_LENGTH,
    IDEMPOTENCY_KEY_MAX_LENGTH,
    PURPOSE_MAX_LENGTH,
)

from ._placement import close_resting_placement, lock_active_loan, lock_active_placement
from .change_state import ChangeConditionInput, change_condition
from .place_equipment import PlaceEquipmentInput, place_equipment

MAX_BATCH_ITEMS = 50


@dataclass(frozen=True, slots=True)
class HandOverEquipmentInput:
    equipment_id: int
    due_at: datetime
    borrower_id: int | None = None
    borrower_name: str = ""
    borrower_contact: str = ""
    purpose: str = ""
    condition_out: str = ""
    booking_id: int | None = None


@dataclass(frozen=True, slots=True)
class LendEquipmentBatchInput:
    equipment_ids: tuple[int, ...]
    due_at: datetime
    borrower_id: int | None = None
    borrower_name: str = ""
    borrower_contact: str = ""
    purpose: str = ""
    conditions_out: tuple[tuple[int, str], ...] = ()
    idempotency_key: str = ""


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
class ReturnEquipmentBatchInput:
    items: tuple[ReturnEquipmentInput, ...]


@dataclass(frozen=True, slots=True)
class ExtendLoanInput:
    equipment_id: int
    due_at: datetime


@dataclass(frozen=True, slots=True)
class ExtendLoansInput:
    due_at: datetime
    equipment_ids: tuple[int, ...] = ()
    batch_id: int | None = None


@transaction.atomic
def hand_over_equipment(command: HandOverEquipmentInput, *, actor) -> EquipmentLoan:
    """Open one loan (a one-line batch). The item must be available; see ``unavailable_reasons``."""
    now = timezone.now()
    _ensure_future(command.due_at, now)
    equipment = _lock_equipment((command.equipment_id,))[command.equipment_id]
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
    reasons = unavailable_reasons(equipment, until=command.due_at, now=now, booking=booking)
    if reasons:
        raise EquipmentNotAvailable(details={"reasons": reasons})
    batch = _create_batch(command, actor=actor)
    return _open_loan(equipment, batch, command.due_at, command.condition_out, now=now, actor=actor, booking=booking)


@transaction.atomic
def lend_equipment_batch(command: LendEquipmentBatchInput, *, actor) -> EquipmentLoanBatch:
    """Hand several items to one borrower. All or nothing: any unavailable item refuses the batch."""
    now = timezone.now()
    _ensure_future(command.due_at, now)
    ids = _distinct_ids(command.equipment_ids)
    key = (command.idempotency_key or "").strip()
    if len(key) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise ValidationError({"idempotency_key": f"Use at most {IDEMPOTENCY_KEY_MAX_LENGTH} characters."})
    request_hash = _request_hash(command, ids)
    if key:
        replay = _find_replay(key, request_hash, actor)
        if replay is not None:
            return replay
    conditions = dict(command.conditions_out)
    unknown = sorted(set(conditions) - set(ids))
    if unknown:
        raise ValidationError({"items": f"Not in equipment_ids: {unknown}."})
    equipment = _lock_equipment(ids, field="equipment_ids")
    problems = {}
    for index, equipment_id in enumerate(ids):
        item = equipment[equipment_id]
        reasons = ["on loan"] if lock_active_loan(item) is not None else []
        reasons += unavailable_reasons(item, until=command.due_at, now=now)
        if reasons:
            problems[f"equipment_ids[{index}]"] = f"{item.sku or item.pk}: " + "; ".join(reasons)
    if problems:
        raise EquipmentNotAvailable(details=problems)
    try:
        with transaction.atomic():
            batch = _create_batch(command, actor=actor, idempotency_key=key, request_hash=request_hash)
    except IntegrityError as error:
        if _constraint(error) != "equipment_loan_batch_idempotency_uniq":
            raise
        replay = _find_replay(key, request_hash, actor)
        if replay is None:
            raise
        return replay
    for equipment_id in ids:
        _open_loan(
            equipment[equipment_id], batch, command.due_at, conditions.get(equipment_id, ""), now=now, actor=actor
        )
    return batch


@transaction.atomic
def return_equipment(command: ReturnEquipmentInput, *, actor) -> EquipmentLoan:
    """Close the active loan, then optionally record the item's condition and where it now is."""
    equipment = _lock_equipment((command.equipment_id,))[command.equipment_id]
    return _return_one(equipment, command, actor=actor)


@transaction.atomic
def return_equipment_batch(command: ReturnEquipmentBatchInput, *, actor) -> list[EquipmentLoan]:
    """Take several items back (any subset of what is out). All or nothing."""
    ids = _distinct_ids(tuple(item.equipment_id for item in command.items), field="items")
    equipment = _lock_equipment(ids, field="items")
    problems = {}
    for index, item in enumerate(command.items):
        unit = equipment[item.equipment_id]
        if lock_active_loan(unit) is None and not _was_returned(unit):
            problems[f"items[{index}].equipment_id"] = f"{unit.sku or unit.pk}: not on loan"
    if problems:
        raise EquipmentNotOnLoan(details=problems)
    return [_return_one(equipment[item.equipment_id], item, actor=actor) for item in command.items]


@transaction.atomic
def extend_loan(command: ExtendLoanInput, *, actor) -> EquipmentLoan:
    """Move the due time of a loan that is not tied to a booking."""
    equipment = _lock_equipment((command.equipment_id,))[command.equipment_id]
    return _extend_one(equipment, command.due_at)


@transaction.atomic
def extend_loans(command: ExtendLoansInput, *, actor) -> list[EquipmentLoan]:
    """Move the due time of several open loans: the given items, or every open line of a batch."""
    if bool(command.equipment_ids) == (command.batch_id is not None):
        raise ValidationError({"non_field_errors": "Give equipment_ids or batch_id, not both."})
    if command.batch_id is not None:
        ids = tuple(
            EquipmentLoan.objects.filter(batch_id=command.batch_id, returned_at__isnull=True)
            .order_by("equipment_id")
            .values_list("equipment_id", flat=True)
        )
        if not ids:
            raise EquipmentNotOnLoan("This batch has no open loans.")
    else:
        ids = _distinct_ids(command.equipment_ids)
    equipment = _lock_equipment(ids, field="equipment_ids")
    return [_extend_one(equipment[equipment_id], command.due_at) for equipment_id in ids]


def unavailable_reasons(
    equipment: Equipment, *, until: datetime, now: datetime, booking: EquipmentBooking | None = None
) -> list[str]:
    """Why an item cannot be handed over now (empty when it can). Caller holds the ``Equipment`` lock.

    An item can leave a room, a station, a noted place, or no recorded place; never a bench.
    """
    reasons = []
    if equipment.lifecycle_state != EquipmentLifecycleState.IN_SERVICE:
        reasons.append(f"lifecycle state is {equipment.lifecycle_state}")
    if equipment.condition != EquipmentCondition.OPERATIONAL:
        reasons.append(f"condition is {equipment.condition}")
    placement = lock_active_placement(equipment)
    if placement is not None and placement.bench_id is not None:
        reasons.append("placed on a bench")
    if equipment.calibration_overdue:
        reasons.append("calibration overdue")
    reserved = EquipmentBooking.objects.filter(
        equipment=equipment,
        status__in=Booking.ACTIVE_STATUSES,
        approval_status__in=Booking.RESERVING_APPROVAL_STATUSES,
        starts_at__lt=until,
        ends_at__gt=now,
    )
    if booking is not None:
        reserved = reserved.exclude(pk=booking.pk)
    if reserved.exists():
        reasons.append("reserved in that period")
    return reasons


def _lock_equipment(ids: Sequence[int], *, field: str = "equipment_id") -> dict[int, Equipment]:
    rows = {
        row.pk: row
        for row in Equipment.objects.select_for_update().filter(pk__in=ids, deleted_at__isnull=True).order_by("pk")
    }
    missing = [equipment_id for equipment_id in ids if equipment_id not in rows]
    if missing:
        if field == "equipment_id":
            raise Equipment.DoesNotExist(f"Equipment {missing[0]} does not exist.")
        raise ValidationError({field: f"Unknown equipment: {missing}."})
    return rows


def _distinct_ids(ids: Sequence[int], *, field: str = "equipment_ids") -> tuple[int, ...]:
    if not ids:
        raise ValidationError({field: "Give at least one equipment item."})
    if len(ids) > MAX_BATCH_ITEMS:
        raise ValidationError({field: f"Give at most {MAX_BATCH_ITEMS} equipment items."})
    if len(set(ids)) != len(ids):
        raise ValidationError({field: "An equipment item is listed twice."})
    return tuple(ids)


def _ensure_future(due_at: datetime, now: datetime) -> None:
    if due_at <= now:
        raise ValidationError({"due_at": "The due time must be in the future."})


def _create_batch(command, *, actor, idempotency_key: str = "", request_hash: str = "") -> EquipmentLoanBatch:
    borrower = None
    if command.borrower_id is not None:
        borrower = get_user_model().objects.filter(pk=command.borrower_id, is_active=True).first()
        if borrower is None:
            raise ValidationError({"borrower_id": "Select an active user."})
    name = _text(command.borrower_name, "borrower_name", BORROWER_NAME_MAX_LENGTH)
    if borrower is None and not name:
        raise ValidationError({"borrower_name": "Give a borrower: a user or a name."})
    return EquipmentLoanBatch.objects.create(
        borrower=borrower,
        borrower_name=name,
        borrower_contact=_text(command.borrower_contact, "borrower_contact", 255),
        purpose=_text(command.purpose, "purpose", PURPOSE_MAX_LENGTH),
        created_by=_user(actor),
        idempotency_key=idempotency_key,
        request_hash=request_hash if idempotency_key else "",
    )


def _open_loan(equipment, batch, due_at, condition_out, *, now, actor, booking=None) -> EquipmentLoan:
    condition_out = _text(condition_out, "condition_out", CONDITION_NOTE_MAX_LENGTH)
    close_resting_placement(equipment, actor=actor)
    try:
        with transaction.atomic():
            return EquipmentLoan.objects.create(
                equipment=equipment,
                batch=batch,
                booking=booking,
                handed_over_at=now,
                handed_over_by=_user(actor),
                due_at=due_at,
                condition_out=condition_out,
            )
    except IntegrityError as error:
        if _constraint(error) in {"one_active_loan_per_equipment", "labs_equipmentloan_booking_id_key"}:
            raise EquipmentOnLoan() from error
        raise


def _was_returned(equipment: Equipment) -> bool:
    latest = EquipmentLoan.objects.filter(equipment=equipment).order_by("-handed_over_at", "-id").first()
    return latest is not None and latest.close_reason == LoanCloseReason.RETURNED


def _return_one(equipment: Equipment, command: ReturnEquipmentInput, *, actor) -> EquipmentLoan:
    condition_in = _text(command.condition_in, "condition_in", CONDITION_NOTE_MAX_LENGTH)
    if command.condition is not None and command.condition not in EquipmentCondition.values:
        raise ValidationError({"condition": "Select a valid condition."})
    loan = lock_active_loan(equipment)
    if loan is None:
        latest = EquipmentLoan.objects.filter(equipment=equipment).order_by("-handed_over_at", "-id").first()
        if latest is not None and latest.close_reason == LoanCloseReason.RETURNED:
            return latest
        raise EquipmentNotOnLoan()
    loan.returned_at = timezone.now()
    loan.received_by = _user(actor)
    loan.condition_in = condition_in
    loan.close_reason = LoanCloseReason.RETURNED
    loan.save(update_fields=("returned_at", "received_by", "condition_in", "close_reason", "modified"))
    if loan.booking_id is not None:
        booking = EquipmentBooking.objects.select_for_update().get(pk=loan.booking_id)
        if booking.status == BookingStatus.IN_PROGRESS:
            ensure_booking_status_transition(current_status=booking.status, target_status=BookingStatus.COMPLETED)
            booking.status = BookingStatus.COMPLETED
            booking.save(update_fields=("status", "modified"))
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


def _extend_one(equipment: Equipment, due_at: datetime) -> EquipmentLoan:
    loan = lock_active_loan(equipment)
    if loan is None:
        raise EquipmentNotOnLoan(f"{equipment.sku or equipment.pk} is not on loan.")
    if loan.due_at == due_at:
        return loan
    if due_at <= timezone.now() or due_at <= loan.handed_over_at:
        raise ValidationError({"due_at": "The due time must be in the future."})
    if loan.booking_id is not None:
        # The booking window and the loan due time move together; the exclusion constraint
        # refuses an extension into the next reservation of the item.
        booking = EquipmentBooking.objects.select_for_update().get(pk=loan.booking_id)
        try:
            with transaction.atomic():
                EquipmentBooking.objects.filter(pk=booking.pk).update(ends_at=due_at, modified=timezone.now())
        except IntegrityError as error:
            if _constraint(error) != "equipment_booking_no_overlap":
                raise
            raise ReservationConflict(
                details={"due_at": f"{equipment.sku or equipment.pk}: reserved by someone else before then"}
            ) from error
    loan.due_at = due_at
    loan.save(update_fields=("due_at", "modified"))
    return loan


def _request_hash(command: LendEquipmentBatchInput, ids: Sequence[int]) -> str:
    body = {
        "equipment_ids": sorted(ids),
        "due_at": command.due_at.isoformat(),
        "borrower_id": command.borrower_id,
        "borrower_name": command.borrower_name.strip(),
        "borrower_contact": command.borrower_contact.strip(),
        "purpose": command.purpose.strip(),
        "conditions_out": sorted((key, value.strip()) for key, value in command.conditions_out),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def _find_replay(key: str, request_hash: str, actor) -> EquipmentLoanBatch | None:
    existing = EquipmentLoanBatch.objects.filter(created_by=_user(actor), idempotency_key=key).first()
    if existing is None:
        return None
    if existing.request_hash != request_hash:
        raise LoanIdempotencyKeyReuse()
    return existing


def _constraint(error: IntegrityError) -> str | None:
    return getattr(getattr(error.__cause__, "diag", None), "constraint_name", None)


def _text(value: str, field: str, limit: int) -> str:
    text = (value or "").strip()
    if len(text) > limit:
        raise ValidationError({field: f"Use at most {limit} characters."})
    return text


def _user(actor):
    return actor if getattr(actor, "is_authenticated", False) else None


__all__ = (
    "ExtendLoanInput",
    "ExtendLoansInput",
    "HandOverEquipmentInput",
    "LendEquipmentBatchInput",
    "ReturnEquipmentBatchInput",
    "ReturnEquipmentInput",
    "extend_loan",
    "extend_loans",
    "hand_over_equipment",
    "lend_equipment_batch",
    "return_equipment",
    "return_equipment_batch",
    "unavailable_reasons",
)
