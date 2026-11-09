"""Stable bench booking business errors."""


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


class LabProjectNotFound(NotFound):
    """Raised when a lab project does not exist."""

    code = "lab_project_not_found"
    default_message = "Lab project not found."


__all__ = [
    "BenchBookingConflict",
    "BenchBookingIdempotencyKeyReuse",
    "BenchBookingPermissionDenied",
    "LabProjectNotFound",
]
