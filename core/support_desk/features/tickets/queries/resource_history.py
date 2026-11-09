"""Read query selector for resource ticket history."""

from typing import Any

from core.support_desk.contracts import ResourceTicketDTO, ResourceTicketSummaryDTO, SystemState
from core.support_desk.features.tickets.application.policies import visible_tickets
from core.support_desk.models.resource_link import TicketResourceLink
from core.support_desk.models.ticket import SupportTicket


def get_resource_ticket_summary(
    resource_type: str,
    resource_id: str | int,
    *,
    viewer: Any = None,
) -> ResourceTicketSummaryDTO:
    """Retrieve all tickets ever linked to a given resource with incident counts.

    With ``viewer`` set, only tickets that user may see are included (requesters see their own history).
    """
    links = (
        TicketResourceLink.objects.select_related(
            "ticket",
            "ticket__status",
            "ticket__priority",
        )
        .filter(resource_type=resource_type, resource_id=str(resource_id))
        .order_by("-linked_at")
    )
    if viewer is not None:
        visible_ids = visible_tickets(SupportTicket.objects.all(), viewer).values("pk")
        links = links.filter(ticket_id__in=visible_ids)

    tickets_list: list[ResourceTicketDTO] = []
    seen_ticket_ids: set[int] = set()
    open_count = 0

    for link in links:
        ticket = link.ticket
        if ticket.id in seen_ticket_ids:
            continue
        seen_ticket_ids.add(ticket.id)

        dto = ResourceTicketDTO(
            id=ticket.id,
            key=ticket.key,
            subject=ticket.subject,
            status_name=ticket.status.name,
            system_state=ticket.status.system_state,
            priority_name=ticket.priority.name,
            priority_rank=ticket.priority.rank,
            created_at=ticket.created_at,
            is_link_active=link.is_active,
        )
        tickets_list.append(dto)

        if ticket.status.system_state != SystemState.DONE.value:
            open_count += 1

    return ResourceTicketSummaryDTO(
        open_count=open_count,
        total_count=len(tickets_list),
        tickets=tuple(tickets_list),
    )
