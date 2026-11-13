"""Reserve equipment for a later window, change or cancel it, hand it over, expire it.

Coordinator-only (equipment booking revision 2). One ``EquipmentBooking`` per item, grouped under
a loan slip (``EquipmentLoanBatch``) that carries the borrower and purpose. Reservations are
created approved.

Race guard: every involved ``Equipment`` row locked in one query ordered by pk, then the slip,
then booking rows; ``equipment_booking_no_overlap`` refuses overlapping windows in PostgreSQL.
Commands are all-or-nothing. Idempotency: creation replays by ``idempotency_key``; cancelling or
handing over lines that are already cancelled or handed over returns them unchanged.
"""

import hashlib
import json
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.equipment.exceptions import (
    EquipmentNotAvailable,
    LoanIdempotencyKeyReuse,
    ReservationConflict,
    ReservationNotOpen,
)
from core.labs.models import (
    Booking,
    BookingApprovalStatus,
    BookingStatus,
    Equipment,
    EquipmentBooking,
    EquipmentLifecycleState,
    EquipmentLoan,
    EquipmentLoanBatch,
    ResourceDowntime,
    ensure_booking_status_transition,
)
from core.labs.models.resource.equipment.loan import IDEMPOTENCY_KEY_MAX_LENGTH

from ._placement import lock_active_loan, lock_active_placement
from .loans import (
    _constraint,
    _create_batch,
    _distinct_ids,
    _lock_equipment,
    _open_loan,
    _text,
    _user,
    unavailable_reasons,
)

EXPIRY_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class ReserveEquipmentBatchInput:
    equipment_ids: tuple[int, ...]
    starts_at: datetime
    ends_at: datetime
    borrower_id: int | None = None
    borrower_name: str = ""
    borrower_contact: str = ""
    purpose: str = ""
    idempotency_key: str = ""


@dataclass(frozen=True, slots=True)
class UpdateReservationInput:
    batch_id: int
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    add_equipment_ids: tuple[int, ...] = ()
    remove_equipment_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class CancelReservationInput:
    batch_id: int
    reason: str
    equipment_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class HandOverReservationInput:
    batch_id: int
    equipment_ids: tuple[int, ...] = ()
    conditions_out: tuple[tuple[int, str], ...] = ()


@transaction.atomic
def reserve_equipment_batch(command: ReserveEquipmentBatchInput, *, actor) -> EquipmentLoanBatch:
    """Reserve several items for one borrower and window. All or nothing."""
    now = timezone.now()
    _ensure_window(command.starts_at, command.ends_at, now)
    ids = _distinct_ids(command.equipment_ids)
    key = (command.idempotency_key or "").strip()
    if len(key) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise ValidationError({"idempotency_key": f"Use at most {IDEMPOTENCY_KEY_MAX_LENGTH} characters."})
    request_hash = _request_hash(command, ids)
    if key:
        replay = _find_replay(key, request_hash, actor)
        if replay is not None:
            return replay
    equipment = _lock_equipment(ids, field="equipment_ids")
    _raise_if_problems(ids, equipment, command.starts_at, command.ends_at, field="equipment_ids")
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
        _create_booking(equipment[equipment_id], batch, command.starts_at, command.ends_at, now=now, actor=actor)
    return batch


@transaction.atomic
def update_reservation(command: UpdateReservationInput, *, actor) -> EquipmentLoanBatch:
    """Move the window of the reserved lines, add items, or drop items. All or nothing."""
    now = timezone.now()
    open_ids = _reserved_equipment_ids(command.batch_id)
    add = tuple(command.add_equipment_ids)
    remove = tuple(command.remove_equipment_ids)
    if not open_ids:
        raise ReservationNotOpen()
    if set(add) & set(open_ids):
        raise ValidationError({"add_equipment_ids": "An item is already reserved on this slip."})
    if set(remove) - set(open_ids):
        raise ValidationError({"remove_equipment_ids": "Only reserved items of this slip can be removed."})
    if len(set(add)) != len(add) or len(set(remove)) != len(remove):
        raise ValidationError({"non_field_errors": "An equipment item is listed twice."})
    equipment = _lock_equipment(tuple(open_ids) + add, field="add_equipment_ids")
    batch = EquipmentLoanBatch.objects.select_for_update().get(pk=command.batch_id)
    lines = list(
        EquipmentBooking.objects.select_for_update().filter(batch=batch, status=BookingStatus.RESERVED).order_by("pk")
    )
    starts_at = command.starts_at or lines[0].starts_at
    ends_at = command.ends_at or lines[0].ends_at
    _ensure_window(starts_at, ends_at, now)
    keep = [line for line in lines if line.equipment_id not in remove]
    if not keep and not add:
        raise ValidationError({"remove_equipment_ids": "Cancel the reservation instead of removing every item."})
    _raise_if_problems(
        tuple(line.equipment_id for line in keep) + add, equipment, starts_at, ends_at, field="equipment", batch=batch
    )
    for line in lines:
        if line.equipment_id in remove:
            _cancel(line, "Removed from the reservation.")
    try:
        with transaction.atomic():
            for line in keep:
                if (line.starts_at, line.ends_at) != (starts_at, ends_at):
                    EquipmentBooking.objects.filter(pk=line.pk).update(
                        starts_at=starts_at, ends_at=ends_at, modified=now
                    )
    except IntegrityError as error:
        if _constraint(error) != "equipment_booking_no_overlap":
            raise
        raise ReservationConflict() from error
    for equipment_id in add:
        _create_booking(equipment[equipment_id], batch, starts_at, ends_at, now=now, actor=actor)
    return batch


@transaction.atomic
def cancel_reservation(command: CancelReservationInput, *, actor) -> EquipmentLoanBatch:
    """Cancel the reserved lines of a slip (all, or the listed items) with a reason."""
    reason = _text(command.reason, "reason", 2000)
    if not reason:
        raise ValidationError({"reason": "Give a reason for the cancellation."})
    lines_by_item = {
        line.equipment_id: line for line in EquipmentBooking.objects.filter(batch_id=command.batch_id).order_by("pk")
    }
    if not lines_by_item:
        raise EquipmentLoanBatch.DoesNotExist(f"No reservation {command.batch_id}.")
    selected = tuple(command.equipment_ids) or tuple(lines_by_item)
    unknown = sorted(set(selected) - set(lines_by_item))
    if unknown:
        raise ValidationError({"equipment_ids": f"Not reserved on this slip: {unknown}."})
    _lock_equipment(selected, field="equipment_ids")
    batch = EquipmentLoanBatch.objects.select_for_update().get(pk=command.batch_id)
    lines = EquipmentBooking.objects.select_for_update().filter(batch=batch, equipment_id__in=selected).order_by("pk")
    for line in lines:
        if line.status == BookingStatus.CANCELLED:
            continue
        if line.status != BookingStatus.RESERVED:
            raise ReservationNotOpen(f"{line.booking_code} is {line.status}; only reserved lines can be cancelled.")
        _cancel(line, reason)
    return batch


@transaction.atomic
def hand_over_reservation(command: HandOverReservationInput, *, actor) -> EquipmentLoanBatch:
    """Hand over reserved items (all, or the listed ones); each loan is due at the reservation end.

    All or nothing over the selected lines. Lines already handed over are left as they are.
    """
    now = timezone.now()
    lines_by_item = {
        line.equipment_id: line
        for line in EquipmentBooking.objects.filter(
            batch_id=command.batch_id, status__in=(BookingStatus.RESERVED, BookingStatus.IN_PROGRESS)
        ).order_by("pk")
    }
    selected = tuple(command.equipment_ids) or tuple(lines_by_item)
    if not selected:
        raise ReservationNotOpen()
    unknown = sorted(set(selected) - set(lines_by_item))
    if unknown:
        raise ValidationError({"equipment_ids": f"Not open on this slip: {unknown}."})
    conditions = dict(command.conditions_out)
    if set(conditions) - set(selected):
        raise ValidationError({"items": "Condition notes given for items that are not handed over."})
    equipment = _lock_equipment(selected, field="equipment_ids")
    batch = EquipmentLoanBatch.objects.select_for_update().get(pk=command.batch_id)
    lines = {
        line.equipment_id: line
        for line in EquipmentBooking.objects.select_for_update().filter(batch=batch, equipment_id__in=selected)
    }
    to_hand_over = []
    problems = {}
    for index, equipment_id in enumerate(selected):
        line, item = lines[equipment_id], equipment[equipment_id]
        if line.status == BookingStatus.IN_PROGRESS:
            continue  # already handed over
        reasons = []
        if line.status != BookingStatus.RESERVED:
            reasons.append(f"reservation is {line.status}")
        if line.ends_at <= now:
            reasons.append("reservation has ended")
        current = lock_active_loan(item)
        if current is not None and current.booking_id != line.pk:
            reasons.append("on loan")
        reasons += unavailable_reasons(item, until=line.ends_at, now=now, booking=line)
        if reasons:
            problems[f"equipment_ids[{index}]"] = f"{item.sku or item.pk}: " + "; ".join(reasons)
        else:
            to_hand_over.append(line)
    if problems:
        raise EquipmentNotAvailable(details=problems)
    for line in to_hand_over:
        ensure_booking_status_transition(current_status=line.status, target_status=BookingStatus.IN_PROGRESS)
        line.status = BookingStatus.IN_PROGRESS
        line.last_modified_by = _user(actor)
        line.save(update_fields=("status", "last_modified_by", "modified"))
        _open_loan(
            equipment[line.equipment_id],
            batch,
            line.ends_at,
            conditions.get(line.equipment_id, ""),
            now=now,
            actor=actor,
            booking=line,
        )
    return batch


def expire_uncollected_reservations(*, now: datetime | None = None, limit: int = EXPIRY_BATCH_SIZE) -> int:
    """Mark reserved lines whose start day (local time) has ended as ``expired``. Safe to re-run.

    Rows locked by a concurrent hand-over are skipped and picked up by the next run.
    """
    now = now or timezone.now()
    today_start = timezone.make_aware(datetime.combine(timezone.localdate(now), time.min))
    expired = 0
    with transaction.atomic():
        rows = list(
            # The loan check is an outer join; lock only the booking rows.
            EquipmentBooking.objects.select_for_update(skip_locked=True, of=("self",))
            .filter(status=BookingStatus.RESERVED, starts_at__lt=today_start, loan__isnull=True)
            .order_by("pk")[:limit]
        )
        for row in rows:
            ensure_booking_status_transition(current_status=row.status, target_status=BookingStatus.EXPIRED)
            row.status = BookingStatus.EXPIRED
            row.save(update_fields=("status", "modified"))
            expired += 1
    return expired


def reservation_problems(
    equipment: Equipment, starts_at: datetime, ends_at: datetime, *, batch: EquipmentLoanBatch | None = None
) -> list[str]:
    """Why an item cannot be reserved for the window (empty when it can). Caller holds the lock."""
    reasons = []
    if not equipment.kind.category.bookable:
        reasons.append("category is not bookable")
    if equipment.lifecycle_state != EquipmentLifecycleState.IN_SERVICE:
        reasons.append(f"lifecycle state is {equipment.lifecycle_state}")
    # A window with a known end blocks the period. An open-ended window (repair of unknown length) is
    # checked at hand-over, like the condition always was (resource-status-and-downtime.md).
    downtime = (
        ResourceDowntime.objects.for_resource(equipment)
        .overlapping(starts_at, ends_at)
        .filter(ends_at__isnull=False)
        .order_by("starts_at")
        .first()
    )
    if downtime is not None:
        reasons.append(
            f"{downtime.get_condition_display().lower()} from {timezone.localtime(downtime.starts_at):%Y-%m-%d %H:%M}"
        )
    placement = lock_active_placement(equipment)
    if placement is not None and placement.bench_id is not None:
        reasons.append("placed on a bench")
    loan = EquipmentLoan.objects.filter(equipment=equipment, returned_at__isnull=True).first()
    if loan is not None and loan.due_at > starts_at and (batch is None or loan.batch_id != batch.pk):
        reasons.append(f"on loan until {timezone.localtime(loan.due_at):%Y-%m-%d %H:%M}")
    overlapping = EquipmentBooking.objects.filter(
        equipment=equipment,
        status__in=Booking.ACTIVE_STATUSES,
        approval_status__in=Booking.RESERVING_APPROVAL_STATUSES,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    )
    if batch is not None:
        overlapping = overlapping.exclude(batch=batch)
    for other in overlapping.order_by("starts_at")[:3]:
        reasons.append(
            f"reserved {timezone.localtime(other.starts_at):%Y-%m-%d %H:%M} to {timezone.localtime(other.ends_at):%Y-%m-%d %H:%M}"
        )
    return reasons


def _raise_if_problems(ids, equipment, starts_at, ends_at, *, field: str, batch=None) -> None:
    problems = {}
    for index, equipment_id in enumerate(ids):
        item = equipment[equipment_id]
        reasons = reservation_problems(item, starts_at, ends_at, batch=batch)
        if reasons:
            problems[f"{field}[{index}]"] = f"{item.sku or item.pk}: " + "; ".join(reasons)
    if problems:
        raise ReservationConflict(details=problems)


def _create_booking(equipment, batch, starts_at, ends_at, *, now, actor) -> EquipmentBooking:
    user = _user(actor)
    try:
        with transaction.atomic():
            return EquipmentBooking.objects.create(
                equipment=equipment,
                batch=batch,
                booking_code=_booking_code(equipment.pk, starts_at),
                starts_at=starts_at,
                ends_at=ends_at,
                status=BookingStatus.RESERVED,
                approval_status=BookingApprovalStatus.APPROVED,
                approved_by=user,
                approved_at=now,
                requester=batch.borrower,
                reason=batch.purpose,
                creator=user,
                last_modified_by=user,
            )
    except IntegrityError as error:
        if _constraint(error) != "equipment_booking_no_overlap":
            raise
        raise ReservationConflict(
            details={"equipment_ids": f"{equipment.sku or equipment.pk}: already reserved"}
        ) from error


def _cancel(line: EquipmentBooking, reason: str) -> None:
    ensure_booking_status_transition(current_status=line.status, target_status=BookingStatus.CANCELLED)
    line.status = BookingStatus.CANCELLED
    line.cancellation_reason = reason
    line.save(update_fields=("status", "cancellation_reason", "modified"))


def _reserved_equipment_ids(batch_id: int) -> list[int]:
    if not EquipmentLoanBatch.objects.filter(pk=batch_id).exists():
        raise EquipmentLoanBatch.DoesNotExist(f"No reservation {batch_id}.")
    return list(
        EquipmentBooking.objects.filter(batch_id=batch_id, status=BookingStatus.RESERVED)
        .order_by("equipment_id")
        .values_list("equipment_id", flat=True)
    )


def _ensure_window(starts_at: datetime, ends_at: datetime, now: datetime) -> None:
    if ends_at <= starts_at:
        raise ValidationError({"ends_at": "The end must be after the start."})
    if ends_at <= now:
        raise ValidationError({"ends_at": "The reservation must end in the future."})
    if ends_at - starts_at > timedelta(days=366):
        raise ValidationError({"ends_at": "A reservation lasts at most a year."})


def _booking_code(equipment_id: int, starts_at: datetime) -> str:
    material = f"{equipment_id}|{starts_at.isoformat()}|{secrets.token_urlsafe(18)}"
    digest = hashlib.sha256(material.encode()).hexdigest()
    return f"EQBOOKING-{digest[:8]}{digest[-6:]}"


def _request_hash(command: ReserveEquipmentBatchInput, ids: Sequence[int]) -> str:
    body = {
        "kind": "reservation",
        "equipment_ids": sorted(ids),
        "starts_at": command.starts_at.isoformat(),
        "ends_at": command.ends_at.isoformat(),
        "borrower_id": command.borrower_id,
        "borrower_name": command.borrower_name.strip(),
        "borrower_contact": command.borrower_contact.strip(),
        "purpose": command.purpose.strip(),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def _find_replay(key: str, request_hash: str, actor) -> EquipmentLoanBatch | None:
    existing = EquipmentLoanBatch.objects.filter(created_by=_user(actor), idempotency_key=key).first()
    if existing is None:
        return None
    if existing.request_hash != request_hash:
        raise LoanIdempotencyKeyReuse()
    return existing


__all__ = (
    "CancelReservationInput",
    "HandOverReservationInput",
    "ReserveEquipmentBatchInput",
    "UpdateReservationInput",
    "cancel_reservation",
    "expire_uncollected_reservations",
    "hand_over_reservation",
    "reservation_problems",
    "reserve_equipment_batch",
    "update_reservation",
)
