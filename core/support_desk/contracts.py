"""Frozen domain types, enums, DTOs, and protocol ports for Support Desk."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


def _label(name: str) -> str:
    """Human label for an enum member name (``STATUS_CHANGED`` -> ``Status Changed``)."""
    return name.replace("_", " ").title()


class SystemState(StrEnum):
    """Fixed system states representing workflow progress."""

    OPEN = "open"
    ACTIVE = "active"
    WAITING = "waiting"
    DONE = "done"

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(item.value, _label(item.name)) for item in cls]


class ResourceType(StrEnum):
    """Allowlisted traceable Lab Mango resource types."""

    ROOM = "room"
    STATION = "station"
    BENCH = "bench"
    EQUIPMENT = "equipment"
    LICENSE = "license"

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(item.value, _label(item.name)) for item in cls]


class _ChoiceEnum(StrEnum):
    """StrEnum that can render Django ``choices``."""

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(item.value, _label(item.name)) for item in cls]


class TicketType(_ChoiceEnum):
    """ITIL-style classification of a ticket (Jira "issue type")."""

    INCIDENT = "incident"  # something is broken / degraded
    SERVICE_REQUEST = "service_request"  # a request for something (access, calibration, a license...)
    PROBLEM = "problem"  # underlying cause behind one or more incidents
    CHANGE = "change"  # planned change to lab infrastructure
    QUESTION = "question"  # how-to / information request


class Impact(_ChoiceEnum):
    """How many people / how much work is affected. Lower value == wider impact."""

    HIGH = "1"  # lab-wide / blocks a whole team or a critical test campaign
    MEDIUM = "2"  # a group of users or one bench/station
    LOW = "3"  # a single user, workaround exists


class Urgency(_ChoiceEnum):
    """How quickly the business needs a fix. Lower value == more urgent."""

    HIGH = "1"
    MEDIUM = "2"
    LOW = "3"


class TicketSource(_ChoiceEnum):
    """Channel through which a ticket entered the desk."""

    WEB = "web"
    EMAIL = "email"
    PHONE = "phone"
    WALK_IN = "walk_in"
    API = "api"
    SYSTEM = "system"


class ResolutionCode(_ChoiceEnum):
    """Why a ticket was resolved (Jira "resolution")."""

    FIXED = "fixed"
    WORKAROUND = "workaround"
    CANNOT_REPRODUCE = "cannot_reproduce"
    DUPLICATE = "duplicate"
    WONT_FIX = "wont_fix"
    USER_ERROR = "user_error"
    VENDOR = "vendor"  # resolved by an external vendor / supplier


class LinkType(_ChoiceEnum):
    """Directional relationship between two tickets (Jira "issue link")."""

    RELATES_TO = "relates_to"
    DUPLICATES = "duplicates"
    BLOCKS = "blocks"
    CAUSED_BY = "caused_by"


#: Inverse wording shown on the *target* ticket of a link.
LINK_INVERSE_LABELS: dict[str, str] = {
    LinkType.RELATES_TO.value: "relates to",
    LinkType.DUPLICATES.value: "is duplicated by",
    LinkType.BLOCKS.value: "is blocked by",
    LinkType.CAUSED_BY.value: "is the cause of",
}


class SlaState(_ChoiceEnum):
    """Computed SLA health of a ticket."""

    NONE = "none"  # no SLA applies (disabled, or priority has no targets)
    OK = "ok"
    AT_RISK = "at_risk"
    BREACHED = "breached"
    PAUSED = "paused"
    MET = "met"


TICKET_TYPE_CHOICES = TicketType.choices()
IMPACT_CHOICES = Impact.choices()
URGENCY_CHOICES = Urgency.choices()
TICKET_SOURCE_CHOICES = TicketSource.choices()
RESOLUTION_CODE_CHOICES = ResolutionCode.choices()
LINK_TYPE_CHOICES = LinkType.choices()


SYSTEM_STATE_CHOICES: list[tuple[str, str]] = SystemState.choices()
RESOURCE_TYPE_CHOICES: list[tuple[str, str]] = ResourceType.choices()


class CommentVisibility(StrEnum):
    """Visibility scope of ticket conversation entries."""

    PUBLIC = "public"
    INTERNAL = "internal"


class AttachmentScanStatus(StrEnum):
    """Security status of uploaded attachments."""

    CLEAN = "clean"
    PENDING = "pending"
    INFECTED = "infected"


class ActivityEventType(StrEnum):
    """Append-only audit log event types."""

    CREATED = "created"
    UPDATED = "updated"
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"
    STATUS_CHANGED = "status_changed"
    PRIORITY_CHANGED = "priority_changed"
    CATEGORY_CHANGED = "category_changed"
    COMMENT_ADDED = "comment_added"
    COMMENT_EDITED = "comment_edited"
    COMMENT_DELETED = "comment_deleted"
    ATTACHMENT_ADDED = "attachment_added"
    ATTACHMENT_REMOVED = "attachment_removed"
    RESOURCE_LINKED = "resource_linked"
    RESOURCE_UNLINKED = "resource_unlinked"
    RESOLVED = "resolved"
    REOPENED = "reopened"
    WATCHER_ADDED = "watcher_added"
    WATCHER_REMOVED = "watcher_removed"
    TICKET_LINKED = "ticket_linked"
    TICKET_UNLINKED = "ticket_unlinked"
    SLA_BREACHED = "sla_breached"
    SLA_PAUSED = "sla_paused"
    SLA_RESUMED = "sla_resumed"
    CSAT_SUBMITTED = "csat_submitted"

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(item.value, _label(item.name)) for item in cls]


class OutboxChannel(StrEnum):
    """Notification channels for the transactional outbox."""

    EMAIL = "email"
    IN_APP = "in_app"


class OutboxStatus(StrEnum):
    """Delivery status of queued notifications."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class SupportRole(StrEnum):
    """Roles recognized in support workflows."""

    REQUESTER = "requester"
    AGENT = "agent"
    ADMIN = "admin"


class ResourceChangeBadge(StrEnum):
    """Visual indication when a live resource differs from its snapshot."""

    NONE = ""
    RENAMED = "renamed"
    MOVED = "moved"
    ARCHIVED = "archived"
    DELETED = "deleted"
    UNLINKED = "unlinked"


@dataclass(frozen=True, slots=True)
class ResourceReferenceDTO:
    """Canonical representation of a resource obtained via its adapter."""

    resource_type: str
    resource_id: str
    name: str
    code: str = ""
    parent_context: str = ""
    detail_url: str = ""
    is_active: bool = True
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResourceTicketDTO:
    """Ticket summary entry for a linked resource."""

    id: int
    key: str
    subject: str
    status_name: str
    system_state: str
    priority_name: str
    priority_rank: int
    created_at: datetime
    is_link_active: bool


@dataclass(frozen=True, slots=True)
class ResourceTicketSummaryDTO:
    """Summary and ticket history for a resource detail page."""

    open_count: int
    total_count: int
    tickets: tuple[ResourceTicketDTO, ...]


class ResourceAdapter(Protocol):
    """Interface implemented by resource adapters."""

    def get_reference(self, resource_id: str | int) -> ResourceReferenceDTO | None:
        """Fetch current reference data for the resource."""
        ...

    def can_view(self, resource_id: str | int, user: Any) -> bool:
        """Check whether the given user is authorized to view this resource."""
        ...

    def search(self, query: str, user: Any) -> list[ResourceReferenceDTO]:
        """Search resources of this type accessible to the user."""
        ...

    def snapshot(self, resource_id: str | int) -> dict[str, Any]:
        """Produce a serializable snapshot dictionary for the resource."""
        ...
