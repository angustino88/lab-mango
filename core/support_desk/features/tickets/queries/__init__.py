"""Read query selectors for support tickets."""

from core.support_desk.features.tickets.queries.get_ticket import get_ticket_by_key
from core.support_desk.features.tickets.queries.list_tickets import list_tickets
from core.support_desk.features.tickets.queries.options import (
    get_category_options,
    get_label_options,
    get_priority_options,
    get_status_options,
    get_team_options,
)
from core.support_desk.features.tickets.queries.resource_history import get_resource_ticket_summary
from core.support_desk.features.tickets.queries.stats import get_queue_stats

__all__ = [
    "get_category_options",
    "get_label_options",
    "get_priority_options",
    "get_queue_stats",
    "get_resource_ticket_summary",
    "get_status_options",
    "get_team_options",
    "get_ticket_by_key",
    "list_tickets",
]
