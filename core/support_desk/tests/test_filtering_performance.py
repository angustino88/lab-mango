"""Shared FilterSpec changes must preserve ticket consumer cardinality."""

import pytest

from core.support_desk.features.tickets.api.filters import TICKET_FILTERS
from core.support_desk.models.resource_link import TicketResourceLink
from core.support_desk.models.ticket import SupportTicket

pytestmark = pytest.mark.django_db


def test_ticket_distinct_is_conditional_and_reverse_links_are_unique(support_setup, requester_user):
    ticket = SupportTicket.objects.create(
        subject="Synthetic filtering regression",
        description="Synthetic only",
        category=support_setup["category"],
        priority=support_setup["priority_med"],
        status=support_setup["status_open"],
        requester=requester_user,
        created_by=requester_user,
    )
    TicketResourceLink.objects.bulk_create(
        [
            TicketResourceLink(ticket=ticket, resource_type="equipment", resource_id=str(i), linked_by=requester_user)
            for i in range(3)
        ]
    )
    base = SupportTicket.objects.filter(pk=ticket.pk)
    assert base.filter(resource_links__resource_type="equipment").count() == 3
    for values in ({}, {"unassigned": True}, {"no_team": False}, {"q": "Synthetic"}):
        result = TICKET_FILTERS.apply(base, values)
        assert result.query.distinct is False
        expected_count = 0 if values == {"no_team": False} else 1
        assert result.count() == expected_count
    result = TICKET_FILTERS.apply(base, {"resource_type": "equipment"})
    assert result.query.distinct is True
    assert list(result.values_list("pk", flat=True)) == [ticket.pk]
    assert TICKET_FILTERS.apply(base.distinct(), {}).query.distinct
