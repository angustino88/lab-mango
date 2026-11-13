"""Shared status vocabularies for lab resources (design: docs/proposals/resource-status-and-downtime.md).

Each enum answers one question and has its own rules (AGENTS.md rule 2):

* ``ResourceLifecycleStatus``: does the lab run the room, station or bench? Stored.
* ``ResourceAccessPolicy``: may anyone use it, or only authorised people? Stored.
* ``ResourceCondition``: does it work now? Computed from ``ResourceDowntime`` windows, never stored.
* ``ResourceActivityStatus``: is someone using it? Computed from bookings, never stored.
* ``ResourceAvailability``: can it be used now, given its parents? Computed, never stored.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class ResourceLifecycleStatus(models.TextChoices):
    PLANNED = "planned", _("Planned")
    IN_SERVICE = "in_service", _("In service")
    RETIRED = "retired", _("Retired")


# Retired is terminal: a room, station or bench that comes back is registered again.
LIFECYCLE_TRANSITIONS = {
    ResourceLifecycleStatus.PLANNED: frozenset({ResourceLifecycleStatus.IN_SERVICE, ResourceLifecycleStatus.RETIRED}),
    ResourceLifecycleStatus.IN_SERVICE: frozenset({ResourceLifecycleStatus.RETIRED}),
    ResourceLifecycleStatus.RETIRED: frozenset(),
}


def ensure_lifecycle_transition(*, current: str, target: str) -> None:
    """The one transition function of the room/station/bench lifecycle (write-safety section 4)."""
    if target not in ResourceLifecycleStatus.values:
        raise ValidationError({"lifecycle_status": "Select planned, in_service or retired."})
    if target != current and target not in LIFECYCLE_TRANSITIONS[ResourceLifecycleStatus(current)]:
        raise ValidationError({"lifecycle_status": f"The lifecycle status cannot change from {current} to {target}."})


class ResourceAccessPolicy(models.TextChoices):
    OPEN = "open", _("Open")
    RESTRICTED = "restricted", _("Restricted")


class ResourceCondition(models.TextChoices):
    OPERATIONAL = "operational", _("Operational")
    IN_MAINTENANCE = "in_maintenance", _("In maintenance")
    OUT_OF_SERVICE = "out_of_service", _("Out of service")


class ResourceActivityStatus(models.TextChoices):
    IDLE = "idle", _("Idle")
    SCHEDULED = "scheduled", _("Scheduled")
    ACTIVE = "active", _("Active")


class ResourceAvailability(models.TextChoices):
    AVAILABLE = "available", _("Available")
    UNAVAILABLE = "unavailable", _("Unavailable")


class LegacyLocationStatus(models.TextChoices):
    """The deprecated seven-value room/station ``status``: computed for old clients, never stored."""

    AVAILABLE = "available", _("Available")
    RESERVED = "reserved", _("Reserved")
    ISSUE = "issue", _("Issue")
    RESTRICTED = "restricted", _("Restricted")
    CLOSED = "closed", _("Closed")
    MAINTENANCE = "maintenance", _("Maintenance")
    RETIRED = "retired", _("Retired")


__all__ = [
    "LIFECYCLE_TRANSITIONS",
    "LegacyLocationStatus",
    "ResourceAccessPolicy",
    "ResourceActivityStatus",
    "ResourceAvailability",
    "ResourceCondition",
    "ResourceLifecycleStatus",
    "ensure_lifecycle_transition",
]
