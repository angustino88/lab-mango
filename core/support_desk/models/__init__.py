"""Models for the Support Desk domain."""

from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.attachment import TicketAttachment
from core.support_desk.models.canned_response import CannedResponse
from core.support_desk.models.category import SupportCategory
from core.support_desk.models.comment import TicketComment
from core.support_desk.models.label import SupportLabel
from core.support_desk.models.outbox import NotificationOutbox
from core.support_desk.models.priority import SupportPriority
from core.support_desk.models.resource_link import TicketResourceLink
from core.support_desk.models.settings import SupportSettings
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.team import SupportTeam
from core.support_desk.models.ticket import SupportTicket, get_next_ticket_number
from core.support_desk.models.ticket_link import TicketLink
from core.support_desk.models.transition import SupportStatusTransition
from core.support_desk.models.watcher import TicketWatcher

__all__ = [
    "CannedResponse",
    "NotificationOutbox",
    "SupportCategory",
    "SupportLabel",
    "SupportPriority",
    "SupportSettings",
    "SupportStatus",
    "SupportStatusTransition",
    "SupportTeam",
    "SupportTicket",
    "TicketActivity",
    "TicketAttachment",
    "TicketComment",
    "TicketLink",
    "TicketResourceLink",
    "TicketWatcher",
    "get_next_ticket_number",
]
