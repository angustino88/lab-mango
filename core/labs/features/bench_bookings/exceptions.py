"""Stable bench booking business errors."""

from datetime import datetime

from core.common.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed


class BenchBookingConflict(Conflict):
    """Raised when a bench booking command conflicts with current domain state."""

    code = "bench_booking_conflict"


class BenchBookingPermissionDenied(Forbidden):
    """Raised when the actor neither owns the booking nor holds a lab manager role."""

    code = "permission_denied"


class BenchBookingIdempotencyKeyReuse(ValidationFailed):
    """Raised when a decision replay key is reused with a different request."""

    code = "idempotency_key_reuse"


class AgentExtensionNotAllowed(ValidationFailed):
    """The requested end time breaks an extension rule. ``details``: ``reason`` and optional ``limit``.

    Reasons (stable): ``already_ended``, ``not_later``, ``too_short``, ``needs_approval``,
    ``bench_not_in_service``. ``limit`` is the earliest (``too_short``) or latest (``needs_approval``)
    end time that would be accepted.
    """

    code = "extension_not_allowed"
    default_message = "The booking cannot be extended to this end time."

    def __init__(self, *, reason: str, limit: datetime | None = None, message: str | None = None) -> None:
        super().__init__(message, details={"reason": reason, "limit": limit})


class AgentExtensionBenchNotFree(Conflict):
    """Another booking holds the bench inside the requested extension. ``details``: ``available_until``."""

    code = "bench_not_free"
    default_message = "The bench is booked by someone else during the requested extension."

    def __init__(self, *, available_until: datetime) -> None:
        super().__init__(details={"available_until": available_until})


class LabProjectNotFound(NotFound):
    """Raised when a lab project does not exist."""

    code = "lab_project_not_found"
    default_message = "Lab project not found."


__all__ = [
    "AgentExtensionBenchNotFree",
    "AgentExtensionNotAllowed",
    "BenchBookingConflict",
    "BenchBookingIdempotencyKeyReuse",
    "BenchBookingPermissionDenied",
    "LabProjectNotFound",
]
