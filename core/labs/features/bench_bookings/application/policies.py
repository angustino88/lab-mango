"""Pure bench booking rules; commands gather facts under locks and call these checks."""

from datetime import datetime, timedelta

from django.core.exceptions import ValidationError

from core.labs.features.bench_bookings.contracts import scheduled_start_is_due
from core.labs.features.bench_bookings.exceptions import AgentExtensionNotAllowed, BenchBookingConflict
from core.labs.models import BookingApprovalStatus, BookingStatus

START_GRACE = timedelta(minutes=10)
ACTIVATION_WINDOW = START_GRACE
MIN_BOOKING_DURATION = timedelta(minutes=10)
LONG_BOOKING_APPROVAL_THRESHOLD = timedelta(hours=4)
# Owner decision O28: each agent extension adds at least this much; there is no maximum per step.
AGENT_EXTENSION_MIN_STEP = MIN_BOOKING_DURATION


def format_duration(duration: timedelta) -> str:
    """Return the smallest whole-unit representation used in validation messages."""
    total_seconds = int(duration.total_seconds())
    if total_seconds % 3600 == 0:
        quantity = total_seconds // 3600
        unit = "hour"
    else:
        quantity = total_seconds // 60
        unit = "minute"
    return f"{quantity} {unit}{'' if quantity == 1 else 's'}"


def ensure_valid_period(starts_at: datetime, ends_at: datetime) -> None:
    if ends_at <= starts_at:
        raise ValidationError({"ends_at": "A booking must end after it starts."})


def ensure_startable(starts_at: datetime, *, now: datetime) -> None:
    if starts_at < now - START_GRACE:
        raise ValidationError(
            {"starts_at": f"A booking cannot start more than {format_duration(START_GRACE)} in the past."}
        )


def ensure_minimum_duration(starts_at: datetime, ends_at: datetime) -> None:
    if ends_at < starts_at + MIN_BOOKING_DURATION:
        raise ValidationError({"ends_at": f"Minimum booking duration is {format_duration(MIN_BOOKING_DURATION)}."})


def default_approval_status(duration: timedelta) -> str:
    return (
        BookingApprovalStatus.PENDING if duration > LONG_BOOKING_APPROVAL_THRESHOLD else BookingApprovalStatus.APPROVED
    )


def approval_status_for_schedule_change(*, duration: timedelta, current_status: str) -> str:
    """Require fresh approval when an update raises a booking above the approval threshold."""
    if duration > LONG_BOOKING_APPROVAL_THRESHOLD:
        return BookingApprovalStatus.PENDING
    return current_status


def ensure_bench_accepts_bookings(bench) -> None:
    if bench.deleted_at is not None:
        raise ValidationError({"bench": "Select an active bench."})
    if bench.lifecycle_status != "in_service":
        raise ValidationError({"bench": "This bench is not in service."})


def ensure_project_exists(*, exists: bool) -> None:
    if not exists:
        raise ValidationError({"project": "Select an existing project."})


def ensure_start_mutable(status: str, *, starts_at_changed: bool, bench_changed: bool) -> None:
    if status == BookingStatus.IN_PROGRESS and (starts_at_changed or bench_changed):
        raise BenchBookingConflict("The start time and bench of an in-progress booking cannot be changed.")


def ensure_no_conflicting_bookings(*, has_conflicts: bool) -> None:
    if has_conflicts:
        raise BenchBookingConflict("The bench is not free for the requested period.")


def is_agent_login_eligible(
    *,
    status: str,
    approval_status: str,
    starts_at: datetime,
    ends_at: datetime,
    booking_bench_id: int,
    computer_bench_id: int | None,
    now: datetime,
) -> bool:
    """Whether an agent may log a user in with this booking on a computer at ``computer_bench_id``.

    A reserved booking is usable from its start until the activation window closes, the moment the
    reconciliation job would expire it. An in-progress booking is usable until it ends.
    """
    if approval_status != BookingApprovalStatus.APPROVED or computer_bench_id != booking_bench_id:
        return False
    if status == BookingStatus.RESERVED:
        return scheduled_start_is_due(starts_at=starts_at, ends_at=ends_at, now=now)
    if status == BookingStatus.IN_PROGRESS:
        return starts_at <= now < ends_at
    return False


def ensure_agent_extension(
    *, starts_at: datetime, current_ends_at: datetime, new_ends_at: datetime, now: datetime
) -> None:
    """Agent extension rules E2, E3, E5 and E6 (bench_bookings/docs/agent-extend.md, decision O28).

    The total booking stays within ``LONG_BOOKING_APPROVAL_THRESHOLD`` so it remains approved and
    the user can still check in again (O21); longer bookings are requested in the web app.
    """
    if current_ends_at <= now:
        raise AgentExtensionNotAllowed(reason="already_ended", message="The booking has already ended.")
    if new_ends_at <= current_ends_at:
        raise AgentExtensionNotAllowed(reason="not_later", message="The new end must be after the current end.")
    latest = starts_at + LONG_BOOKING_APPROVAL_THRESHOLD
    earliest = current_ends_at + AGENT_EXTENSION_MIN_STEP
    if new_ends_at > latest or earliest > latest:
        raise AgentExtensionNotAllowed(
            reason="needs_approval",
            limit=latest,
            message=f"Bookings longer than {format_duration(LONG_BOOKING_APPROVAL_THRESHOLD)} need approval in the web app.",
        )
    if new_ends_at < earliest:
        raise AgentExtensionNotAllowed(
            reason="too_short",
            limit=earliest,
            message=f"Extend by at least {format_duration(AGENT_EXTENSION_MIN_STEP)}.",
        )
