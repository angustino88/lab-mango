"""Domain exceptions for the monitoring event feature."""

from django.core.exceptions import ObjectDoesNotExist

from core.common.domain.errors import Conflict, NotFound, ValidationFailed


class ComputerNotFound(NotFound, ObjectDoesNotExist):
    """Raised when computing equipment is not found."""

    code = "not_found"


class MonitoringEventNotFound(NotFound, ObjectDoesNotExist):
    """Raised when monitoring event is not found."""

    code = "not_found"


class MonitoringEventConflict(Conflict):
    """Raised when duplicate agent report is submitted."""

    code = "monitoring_event_conflict"


class ObservationConflict(Conflict):
    """Raised when a sequence number is reused by a different batch."""

    code = "observation_conflict"


class ObservationSnapshotRequired(ObservationConflict):
    """Raised when an incremental batch cannot be applied on top of the collector cursor.

    The agent recovers by sending a complete snapshot with a newer sequence.
    """

    code = "snapshot_required"


class ObservationKeyReuse(ValidationFailed):
    """Raised when an idempotency key is reused with different content."""

    code = "idempotency_key_reuse"


class ObservationInProgress(Conflict):
    """Raised when an identical request is still being processed."""

    code = "request_in_progress"
