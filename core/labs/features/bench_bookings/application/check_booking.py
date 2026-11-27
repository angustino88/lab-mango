"""Preview whether a bench booking, or a change to one, would be accepted. Writes nothing and takes no locks.

The answer is advice for the moment it is computed: create and update check again under their row locks, so a
booking made between the check and the write is still refused there. Every rule comes from ``policies`` and the
same selectors the commands use, so a preview and the real write report the same problems.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone

from core.common.domain.errors import DomainError
from core.labs.features.bench_bookings.exceptions import BenchBookingConflict
from core.labs.features.bench_bookings.queries import (
    bench_downtime_blocker,
    bench_has_computing,
    bench_parent_blocker,
    conflicting_bench_bookings,
    get_visible_bench_booking,
    may_book_during_downtime,
    project_exists,
)
from core.labs.models import Bench, BenchBooking, BookingApprovalStatus, BookingStatus

from . import policies
from .update_booking import TERMINAL_STATUSES, ensure_can_modify

MAX_OCCURRENCES = 10


@dataclass(frozen=True, slots=True)
class BookingPeriod:
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class CheckBenchBookingInput:
    """A new booking (``booking_id`` empty) or a change to ``booking_id``.

    For a change, omitted fields keep the booking's current values. ``occurrences`` checks the same bench,
    project and reason for several periods (a series); it replaces ``starts_at``/``ends_at`` and is only
    accepted for new bookings.
    """

    bench_id: int | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    project_id: int | None = None
    booking_id: int | None = None
    occurrences: Sequence[BookingPeriod] = ()


@dataclass(frozen=True, slots=True)
class BookingProblem:
    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True, slots=True)
class BookingCheckResult:
    starts_at: datetime
    ends_at: datetime
    is_bookable: bool
    approval_status: str | None
    problems: list[BookingProblem] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BenchBookingCheck:
    results: list[BookingCheckResult]

    @property
    def can_book_all(self) -> bool:
        return all(result.is_bookable for result in self.results)


def check_bench_booking(*, actor: Any, data: CheckBenchBookingInput) -> BenchBookingCheck:
    """Report, per period, whether the booking would be accepted now and which approval it would need."""
    booking = _target_booking(actor=actor, data=data)
    bench_id = data.bench_id if data.bench_id is not None else (booking.bench_id if booking else None)
    if bench_id is None:
        raise ValidationError({"bench_id": "This field is required."})
    periods = _periods(data=data, booking=booking)
    project_id = data.project_id if data.project_id is not None else (booking.project_id if booking else None)

    shared: list[BookingProblem] = []
    bench = Bench.all_objects.filter(pk=bench_id).first()
    if bench is None:
        raise ValidationError({"bench": "Select an existing bench."})
    bench_changed = booking is None or bench_id != booking.bench_id
    if bench_changed:
        _collect(
            shared,
            lambda: policies.ensure_bench_accepts_bookings(bench, parent_blocker=bench_parent_blocker(bench=bench)),
        )
        _collect(
            shared, lambda: policies.ensure_bench_has_computing(has_computing=bench_has_computing(bench_id=bench_id))
        )
    if project_id is not None:
        _collect(shared, lambda: policies.ensure_project_exists(exists=project_exists(project_id=project_id)))
    elif booking is None:
        shared.append(BookingProblem(code="invalid", field="project", message="Select an existing project."))

    # The holder uses the bench: for a change that is the booking's creator, not the editor.
    holder = booking.creator if booking is not None else actor
    lab_operator = may_book_during_downtime(holder)
    now = timezone.now()
    results = [
        _check_period(
            period=period,
            bench=bench,
            booking=booking,
            bench_changed=bench_changed,
            lab_operator=lab_operator,
            shared=shared,
            now=now,
        )
        for period in periods
    ]
    return BenchBookingCheck(results=results)


def _target_booking(*, actor: Any, data: CheckBenchBookingInput) -> BenchBooking | None:
    if data.booking_id is None:
        return None
    if data.occurrences:
        raise ValidationError({"occurrences": "A series can only be checked for a new booking."})
    booking = get_visible_bench_booking(actor=actor, booking_id=data.booking_id)
    ensure_can_modify(actor, booking)
    return booking


def _periods(*, data: CheckBenchBookingInput, booking: BenchBooking | None) -> list[BookingPeriod]:
    if data.occurrences:
        if data.starts_at is not None or data.ends_at is not None:
            raise ValidationError({"occurrences": "Send either starts_at and ends_at, or occurrences."})
        if len(data.occurrences) > MAX_OCCURRENCES:
            raise ValidationError({"occurrences": f"Check at most {MAX_OCCURRENCES} periods at once."})
        return list(data.occurrences)
    starts_at = data.starts_at if data.starts_at is not None else (booking.starts_at if booking else None)
    ends_at = data.ends_at if data.ends_at is not None else (booking.ends_at if booking else None)
    if starts_at is None or ends_at is None:
        raise ValidationError(
            {
                name: "This field is required."
                for name, value in (("starts_at", starts_at), ("ends_at", ends_at))
                if value is None
            }
        )
    return [BookingPeriod(starts_at=starts_at, ends_at=ends_at)]


def _check_period(
    *,
    period: BookingPeriod,
    bench: Bench,
    booking: BenchBooking | None,
    bench_changed: bool,
    lab_operator: bool,
    shared: list[BookingProblem],
    now: datetime,
) -> BookingCheckResult:
    problems = list(shared)
    starts_at, ends_at = period.starts_at, period.ends_at
    starts_changed = booking is None or starts_at != booking.starts_at
    ends_changed = booking is None or ends_at != booking.ends_at
    if booking is not None:
        _collect(problems, lambda: _ensure_booking_changeable(booking, now=now))
        _collect(
            problems,
            lambda: policies.ensure_start_mutable(
                booking.status, starts_at_changed=starts_changed, bench_changed=bench_changed
            ),
        )

    period_valid = _collect(problems, lambda: policies.ensure_valid_period(starts_at, ends_at))
    if period_valid:
        _collect(problems, lambda: policies.ensure_minimum_duration(starts_at, ends_at))
    if starts_changed:
        _collect(problems, lambda: policies.ensure_startable(starts_at, now=now))
    if period_valid and (bench_changed or starts_changed or ends_changed):
        conflicts = conflicting_bench_bookings(
            bench_id=bench.pk,
            starts_at=starts_at,
            ends_at=ends_at,
            exclude_id=booking.pk if booking is not None else None,
        )
        _collect(problems, lambda: policies.ensure_no_conflicting_bookings(has_conflicts=conflicts.exists()))
        _collect(
            problems,
            lambda: policies.ensure_no_downtime(
                bench_downtime_blocker(bench=bench, starts_at=starts_at, ends_at=ends_at, lab_operator=lab_operator)
            ),
        )

    approval_status = None
    if period_valid:
        duration = ends_at - starts_at
        if booking is None:
            approval_status = policies.default_approval_status(duration)
        elif starts_changed or ends_changed:
            approval_status = policies.approval_status_for_schedule_change(
                duration=duration, current_status=booking.approval_status
            )
        else:
            approval_status = booking.approval_status
    return BookingCheckResult(
        starts_at=starts_at,
        ends_at=ends_at,
        is_bookable=not problems,
        approval_status=approval_status,
        problems=problems,
    )


def _ensure_booking_changeable(booking: BenchBooking, *, now: datetime) -> None:
    """The state rules ``update_bench_booking`` applies before a schedule change."""
    if booking.approval_status == BookingApprovalStatus.REJECTED:
        raise BenchBookingConflict("A rejected booking can only be cancelled.")
    if booking.status in TERMINAL_STATUSES:
        raise BenchBookingConflict(f"A {BookingStatus(booking.status).label.lower()} booking cannot be changed.")
    if booking.status == BookingStatus.RESERVED and booking.starts_at + policies.ACTIVATION_WINDOW <= now:
        raise BenchBookingConflict("This booking has expired and cannot be updated.")


def _collect(problems: list[BookingProblem], check) -> bool:
    """Run one policy check; record its failure as problems. Returns whether it passed."""
    try:
        check()
    except ValidationError as error:
        if hasattr(error, "message_dict"):
            for name, messages in error.message_dict.items():
                problems.extend(BookingProblem(code="invalid", field=name, message=message) for message in messages)
        else:
            problems.extend(BookingProblem(code="invalid", message=message) for message in error.messages)
        return False
    except DomainError as error:
        problems.append(BookingProblem(code=error.code, message=error.message))
        return False
    return True
