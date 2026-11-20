"""Downtime commands: schedule (or start), end and cancel a window, and change who may still book
(design rules 1, 3, 4; RS4; booking access: ``docs/proposals/downtime-lab-staff-booking-access.md``).

Race guards: ``lock_target`` locks the resource and every bench it covers before bookings are read
(see ``targets``); same-resource overlap is the ``downtime_no_overlap`` exclusion constraint, mapped to
``DowntimeOverlap``; end and cancel lock the window row; a booking access change locks the target, then
the window row. Idempotency: ending an ended window, cancelling a cancelled one, or setting the booking
access it already has returns it unchanged; a repeated schedule request meets its own window and gets
``DowntimeOverlap``.
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
    DowntimeBookingAccess,
    DowntimeKind,
    DowntimeReason,
    EquipmentBooking,
    ResourceCondition,
    ResourceDowntime,
)
from core.labs.models.resource.base.availability import booking_conflict_details
from core.labs.models.resource.base.downtime import DOWNTIME_CONDITIONS
from core.users.public import LabsRole, users_holding_labs_role

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
    booking_access: str = DowntimeBookingAccess.CLOSED


@dataclass(frozen=True, slots=True)
class DowntimeActionInput:
    downtime_id: int


@dataclass(frozen=True, slots=True)
class ChangeDowntimeBookingAccessInput:
    downtime_id: int
    booking_access: str
    cancel_conflicting_bookings: bool = False


# Bench bookings are the only bookings lab staff can keep making during downtime.
LAB_STAFF_ACCESS_RESOURCE_TYPES = ("room", "station", "bench")


def _validate_booking_access(resource_type: str, booking_access: str) -> dict[str, str]:
    if booking_access not in DowntimeBookingAccess.values:
        return {"booking_access": "Select closed or lab_staff."}
    if booking_access == DowntimeBookingAccess.LAB_STAFF and resource_type not in LAB_STAFF_ACCESS_RESOURCE_TYPES:
        return {"booking_access": "Lab staff access applies to rooms, stations and benches, not equipment."}
    return {}


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
    errors.update(_validate_booking_access(command.resource_type, command.booking_access))
    if errors:
        raise ValidationError(errors)


def _reserving(
    queryset, starts_at: datetime, ends_at: datetime | None, *, booking_access: str = DowntimeBookingAccess.CLOSED
):
    """Reserving bookings in ``queryset`` that overlap the period and the window would block.

    A window open to lab staff does not block bookings created by a current coordinator or administrator
    (the same rule bench booking writers apply to the holder, ``bench_bookings.queries.is_lab_staff``).
    """
    queryset = queryset.filter(
        status__in=Booking.ACTIVE_STATUSES,
        approval_status__in=Booking.RESERVING_APPROVAL_STATUSES,
        ends_at__gt=starts_at,
    )
    if ends_at is not None:
        queryset = queryset.filter(starts_at__lt=ends_at)
    if booking_access == DowntimeBookingAccess.LAB_STAFF:
        queryset = queryset.exclude(creator__in=users_holding_labs_role(LabsRole.COORDINATOR).values("pk"))
    return list(queryset.order_by("pk").values_list("pk", flat=True))


def _resolve_booking_conflicts(
    *,
    bench_booking_ids: list[int],
    equipment_booking_ids: list[int],
    cancel: bool,
    condition: str,
    reason: str,
    actor,
) -> None:
    """Refuse with ``DowntimeBookingConflict`` (RS4), or cancel the bookings when ``cancel`` confirms it."""
    if not bench_booking_ids and not equipment_booking_ids:
        return
    if not cancel:
        raise DowntimeBookingConflict(
            details=booking_conflict_details(
                bench_booking_ids=bench_booking_ids, equipment_booking_ids=equipment_booking_ids
            )
        )
    message = f"Cancelled for {ResourceCondition(condition).label.lower()} ({reason})."
    if bench_booking_ids:
        cancel_bench_bookings_for_downtime(
            actor=actor, data=CancelBookingsForDowntimeInput(tuple(bench_booking_ids), message)
        )
    if equipment_booking_ids:
        cancel_equipment_bookings_for_downtime(
            CancelEquipmentBookingsForDowntimeInput(tuple(equipment_booking_ids), message), actor=actor
        )


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
        _resolve_booking_conflicts(
            bench_booking_ids=_reserving(
                BenchBooking.objects.filter(bench_id__in=target.bench_ids),
                starts_at,
                command.ends_at,
                booking_access=command.booking_access,
            ),
            equipment_booking_ids=_reserving(
                EquipmentBooking.objects.filter(equipment_id__in=target.equipment_ids), starts_at, command.ends_at
            ),
            cancel=command.cancel_conflicting_bookings,
            condition=command.condition,
            reason=command.reason,
            actor=actor,
        )
        window = ResourceDowntime.for_new_resource(
            target.resource,
            condition=command.condition,
            kind=kind,
            reason=command.reason,
            booking_access=command.booking_access,
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


def change_downtime_booking_access(command: ChangeDowntimeBookingAccessInput, *, actor) -> ResourceDowntime:
    """Open a scheduled or current window to lab staff bookings, or close it to everyone.

    Opening (``closed`` → ``lab_staff``) never conflicts. Closing (``lab_staff`` → ``closed``) applies RS4
    to the rest of the window: reserving bench bookings that overlap it from now on (lab staff bookings made
    while it was open) are refused with ``DowntimeBookingConflict`` unless ``cancel_conflicting_bookings``
    confirms their cancellation in the same transaction. An ended or cancelled window cannot change.

    Race guard: the covered benches are locked (``lock_target``, the downtime lock order) before the window
    row and before bookings are read, so a bench booking writer either commits first and is seen here, or
    waits and then reads the new access. Idempotent: the current value returns the window unchanged.
    """
    window = ResourceDowntime.objects.select_related("resource_content_type").get(pk=command.downtime_id)
    resource_type = _resource_type_of(window)
    errors = _validate_booking_access(resource_type, command.booking_access)
    if errors:
        raise ValidationError(errors)
    if window.booking_access == command.booking_access:
        return window
    with transaction.atomic():
        target = lock_target(resource_type, int(window.resource_object_id))
        window = _lock_window(command.downtime_id)
        if window.booking_access == command.booking_access:
            return window
        now = timezone.now()
        if window.is_cancelled:
            raise DowntimeNotAllowed("A cancelled window cannot change who may book.")
        if window.ends_at is not None and window.ends_at <= now:
            raise DowntimeNotAllowed("An ended window cannot change who may book.")
        if command.booking_access == DowntimeBookingAccess.CLOSED:
            _resolve_booking_conflicts(
                bench_booking_ids=_reserving(
                    BenchBooking.objects.filter(bench_id__in=target.bench_ids),
                    max(window.starts_at, now),
                    window.ends_at,
                ),
                equipment_booking_ids=[],
                cancel=command.cancel_conflicting_bookings,
                condition=window.condition,
                reason=window.reason,
                actor=actor,
            )
        window.booking_access = command.booking_access
        window.save(actor=actor, update_fields=("booking_access", "modified"))
    return window


def _resource_type_of(window: ResourceDowntime) -> str:
    model = window.resource_content_type.model_class()
    for name, resource_model in RESOURCE_MODELS.items():
        if model is resource_model:
            return name
    raise DowntimeNotAllowed("This window is not linked to a room, station, bench or equipment unit.")


__all__ = [
    "ChangeDowntimeBookingAccessInput",
    "DowntimeActionInput",
    "ScheduleDowntimeInput",
    "cancel_downtime",
    "change_downtime_booking_access",
    "end_downtime",
    "schedule_downtime",
]
