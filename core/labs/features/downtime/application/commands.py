"""Downtime commands: schedule (or start), end and cancel a window (design rules 1, 3, 4; RS4).

Race guards: ``lock_target`` locks the resource and every bench it covers before bookings are read
(see ``targets``); same-resource overlap is the ``downtime_no_overlap`` exclusion constraint, mapped to
``DowntimeOverlap``; end and cancel lock the window row. Idempotency: ending an ended window or
cancelling a cancelled one returns it unchanged; a repeated schedule request meets its own window and
gets ``DowntimeOverlap``.
"""

from dataclasses import dataclass
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.bench_bookings.public import (
    CancelBookingsForDowntimeInput,
    cancel_bench_bookings_for_downtime,
)
from core.labs.features.downtime.exceptions import DowntimeBookingConflict, DowntimeNotAllowed, DowntimeOverlap
from core.labs.features.equipment.public import (
    CancelEquipmentBookingsForDowntimeInput,
    cancel_equipment_bookings_for_downtime,
)
from core.labs.models import (
    BenchBooking,
    Booking,
    DowntimeKind,
    DowntimeReason,
    EquipmentBooking,
    ResourceCondition,
    ResourceDowntime,
)
from core.labs.models.resource.base.availability import booking_conflict_details
from core.labs.models.resource.base.downtime import DOWNTIME_CONDITIONS

from .targets import RESOURCE_MODELS, lock_target

NOTES_MAX_LENGTH = 2000


@dataclass(frozen=True, slots=True)
class ScheduleDowntimeInput:
    resource_type: str
    resource_id: int
    condition: str
    reason: str = DowntimeReason.OTHER
    kind: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    notes: str = ""
    cancel_conflicting_bookings: bool = False


@dataclass(frozen=True, slots=True)
class DowntimeActionInput:
    downtime_id: int


def _validate(command: ScheduleDowntimeInput, *, starts_at: datetime) -> None:
    errors = {}
    if command.resource_type not in RESOURCE_MODELS:
        errors["resource_type"] = f"Select one of: {', '.join(RESOURCE_MODELS)}."
    if command.condition not in DOWNTIME_CONDITIONS:
        errors["condition"] = "Select in_maintenance or out_of_service."
    if command.reason not in DowntimeReason.values:
        errors["reason"] = "Select a valid reason."
    if command.kind is not None and command.kind not in DowntimeKind.values:
        errors["kind"] = "Select planned or unplanned."
    if command.ends_at is not None and command.ends_at <= starts_at:
        errors["ends_at"] = "The end must be after the start."
    if len(command.notes or "") > NOTES_MAX_LENGTH:
        errors["notes"] = f"Use at most {NOTES_MAX_LENGTH} characters."
    if errors:
        raise ValidationError(errors)


def _reserving(queryset, starts_at: datetime, ends_at: datetime | None):
    queryset = queryset.filter(
        status__in=Booking.ACTIVE_STATUSES,
        approval_status__in=Booking.RESERVING_APPROVAL_STATUSES,
        ends_at__gt=starts_at,
    )
    if ends_at is not None:
        queryset = queryset.filter(starts_at__lt=ends_at)
    return list(queryset.order_by("pk").values_list("pk", flat=True))


def schedule_downtime(command: ScheduleDowntimeInput, *, actor) -> ResourceDowntime:
    """Record a window for a room, station, bench or equipment unit, refusing overlapping bookings.

    ``kind`` defaults to ``planned`` for a window that starts later and ``unplanned`` otherwise.
    """
    now = timezone.now()
    starts_at = command.starts_at or now
    _validate(command, starts_at=starts_at)
    kind = command.kind or (DowntimeKind.PLANNED if starts_at > now else DowntimeKind.UNPLANNED)
    with transaction.atomic():
        target = lock_target(command.resource_type, command.resource_id)
        if not target.in_service:
            raise DowntimeNotAllowed("Downtime can be recorded only for a resource that is in service.")
        bench_booking_ids = _reserving(
            BenchBooking.objects.filter(bench_id__in=target.bench_ids), starts_at, command.ends_at
        )
        equipment_booking_ids = _reserving(
            EquipmentBooking.objects.filter(equipment_id__in=target.equipment_ids), starts_at, command.ends_at
        )
        if bench_booking_ids or equipment_booking_ids:
            if not command.cancel_conflicting_bookings:
                raise DowntimeBookingConflict(
                    details=booking_conflict_details(
                        bench_booking_ids=bench_booking_ids, equipment_booking_ids=equipment_booking_ids
                    )
                )
            reason = f"Cancelled for {ResourceCondition(command.condition).label.lower()} ({command.reason})."
            if bench_booking_ids:
                cancel_bench_bookings_for_downtime(
                    actor=actor, data=CancelBookingsForDowntimeInput(tuple(bench_booking_ids), reason)
                )
            if equipment_booking_ids:
                cancel_equipment_bookings_for_downtime(
                    CancelEquipmentBookingsForDowntimeInput(tuple(equipment_booking_ids), reason), actor=actor
                )
        window = ResourceDowntime.for_new_resource(
            target.resource,
            condition=command.condition,
            kind=kind,
            reason=command.reason,
            starts_at=starts_at,
            ends_at=command.ends_at,
            notes=(command.notes or "").strip(),
        )
        window.full_clean(exclude=("resource_content_type",), validate_constraints=False)
        try:
            with transaction.atomic():
                window.save(actor=actor)
        except IntegrityError as error:
            if getattr(getattr(error.__cause__, "diag", None), "constraint_name", None) != "downtime_no_overlap":
                raise
            raise DowntimeOverlap() from error
    return window


def _lock_window(downtime_id: int) -> ResourceDowntime:
    return ResourceDowntime.objects.select_for_update().get(pk=downtime_id)


@transaction.atomic
def end_downtime(command: DowntimeActionInput, *, actor) -> ResourceDowntime:
    """End a window that has started, now. An already ended window is returned unchanged."""
    window = _lock_window(command.downtime_id)
    now = timezone.now()
    if window.is_cancelled:
        raise DowntimeNotAllowed("A cancelled window cannot be ended.")
    if window.ends_at is not None and window.ends_at <= now:
        return window
    if window.starts_at > now:
        raise DowntimeNotAllowed("This window has not started. Cancel it instead.")
    window.end(at=now, actor=actor)
    return window


@transaction.atomic
def cancel_downtime(command: DowntimeActionInput, *, actor) -> ResourceDowntime:
    """Cancel a window that has not started. An already cancelled window is returned unchanged."""
    window = _lock_window(command.downtime_id)
    if window.is_cancelled:
        return window
    if window.starts_at <= timezone.now():
        raise DowntimeNotAllowed("This window has started. End it instead.")
    window.cancel(at=timezone.now(), actor=actor)
    return window


__all__ = [
    "DowntimeActionInput",
    "ScheduleDowntimeInput",
    "cancel_downtime",
    "end_downtime",
    "schedule_downtime",
]
