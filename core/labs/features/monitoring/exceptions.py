"""Domain exceptions for the monitoring event feature."""
from django.core.exceptions import ObjectDoesNotExist

from core.common.domain.errors import Conflict, NotFound


class ComputerNotFound(NotFound, ObjectDoesNotExist):
    """Raised when computing equipment is not found."""

    code = "not_found"


class MonitoringEventNotFound(NotFound, ObjectDoesNotExist):
    """Raised when monitoring event is not found."""

    code = "not_found"


class MonitoringEventConflict(Conflict):
    """Raised when duplicate agent report is submitted."""

    code = "monitoring_event_conflict"
