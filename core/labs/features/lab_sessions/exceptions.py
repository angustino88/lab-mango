"""Stable lab session business errors."""

from core.common.domain.errors import Conflict, ValidationFailed


class SessionLogConflict(Conflict):
    """The agent reused an event id for a session with different values."""

    code = "session_log_conflict"
    default_message = "This event id is already stored with different session values."


class SessionLogEquipmentUnavailable(Conflict):
    """The computer the agent is enrolled for is deleted."""

    code = "equipment_unavailable"
    default_message = "The computer this agent is enrolled for is deleted."


class SessionLogInvalid(ValidationFailed):
    """A session value is invalid or outside the accepted limits; ``details`` maps field to message."""

    code = "validation_failed"
    default_message = "Invalid session log."


__all__ = ["SessionLogConflict", "SessionLogEquipmentUnavailable", "SessionLogInvalid"]
