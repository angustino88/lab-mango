"""Small helpers shared by the Support Desk command use cases."""

from typing import Any

from core.support_desk.exceptions import TicketNotFoundError
from core.support_desk.features.tickets.application.policies import can_view_ticket
from core.support_desk.models.ticket import SupportTicket


def actor_display_name(actor: Any, default: str = "Unknown") -> str:
    """Best human-readable name for an actor (``System`` when there is none)."""
    if actor is None:
        return "System"
    full_name = getattr(actor, "get_full_name", lambda: "")()
    return full_name or getattr(actor, "username", "") or default


def actor_or_none(actor: Any) -> Any:
    """Return the actor if it is a persisted user, else ``None`` (for nullable FKs)."""
    return actor if getattr(actor, "pk", None) else None


def get_ticket_for_actor(ticket_key: str, actor: Any, *, select_related: tuple[str, ...] = ()) -> SupportTicket:
    """Load a ticket the actor is allowed to see, or raise :class:`TicketNotFoundError`.

    Invisible tickets deliberately look identical to non-existent ones so keys cannot be enumerated.
    """
    qs = SupportTicket.objects.all()
    if select_related:
        qs = qs.select_related(*select_related)
    ticket = qs.filter(key=ticket_key).first()
    if ticket is None or not can_view_ticket(actor, ticket):
        raise TicketNotFoundError(f"Ticket {ticket_key} not found.")
    return ticket
