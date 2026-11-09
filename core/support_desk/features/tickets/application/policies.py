"""Authorization and business policies for Support Desk."""

from datetime import timedelta
from typing import Any

from django.db.models import Q, QuerySet
from django.utils import timezone

from core.support_desk.contracts import CommentVisibility, SupportRole, SystemState
from core.support_desk.features.tickets.application.adapters import get_adapter
from core.support_desk.models.comment import TicketComment
from core.support_desk.models.settings import SupportSettings
from core.support_desk.models.ticket import SupportTicket
from core.support_desk.models.transition import SupportStatusTransition
from core.support_desk.models.watcher import TicketWatcher


def resolve_support_role(user: Any) -> SupportRole | None:
    """Resolve the effective support role for a given user."""
    if not user or not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "is_superuser", False):
        return SupportRole.ADMIN

    # Check Labs roles
    try:
        from core.users.public import LabsRole, effective_labs_roles

        roles = effective_labs_roles(user)
        if LabsRole.ADMIN in roles:
            return SupportRole.ADMIN
        if LabsRole.COORDINATOR in roles:
            return SupportRole.AGENT
    except Exception:
        pass

    # Check group membership
    if user.groups.filter(name__in=["Support Administrator", "Administrator", "admin"]).exists():
        return SupportRole.ADMIN
    if user.groups.filter(name__in=["Support Agent", "Coordinator", "coord"]).exists():
        return SupportRole.AGENT

    return SupportRole.REQUESTER


def is_support_admin(user: Any) -> bool:
    return resolve_support_role(user) == SupportRole.ADMIN


def is_support_agent(user: Any) -> bool:
    return resolve_support_role(user) in (SupportRole.AGENT, SupportRole.ADMIN)


def visible_tickets(queryset: QuerySet[SupportTicket], user: Any) -> QuerySet[SupportTicket]:
    """Restrict ``queryset`` to tickets ``user`` may see.

    Agents and administrators see every ticket. Requesters see tickets they requested, created, or watch.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return queryset.none()
    if is_support_agent(user):
        return queryset
    watched = TicketWatcher.objects.filter(user=user).values("ticket_id")
    return queryset.filter(Q(requester=user) | Q(created_by=user) | Q(pk__in=watched))


def can_view_ticket(user: Any, ticket: SupportTicket) -> bool:
    """Object-level counterpart of :func:`visible_tickets`."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if is_support_agent(user):
        return True
    if ticket.requester_id == user.pk or ticket.created_by_id == user.pk:
        return True
    return TicketWatcher.objects.filter(ticket=ticket, user=user).exists()


def can_manage_watchers(user: Any, ticket: SupportTicket, target_user_id: int) -> bool:
    """Agents manage anyone's subscription; others may only (un)subscribe themselves on a ticket they can see."""
    if is_support_agent(user):
        return True
    return target_user_id == user.pk and can_view_ticket(user, ticket)


def can_link_tickets(user: Any) -> bool:
    return is_support_agent(user)


def can_triage_ticket(user: Any) -> bool:
    """Change type, impact, urgency, team, labels, parent, due date."""
    return is_support_agent(user)


def can_submit_csat(user: Any, ticket: SupportTicket) -> bool:
    return bool(user and getattr(user, "is_authenticated", False) and ticket.requester_id == user.pk)


def can_view_internal_notes(user: Any) -> bool:
    return is_support_agent(user)


def can_view_restricted_attachments(user: Any) -> bool:
    return is_support_agent(user)


def can_create_ticket_on_behalf(user: Any) -> bool:
    return is_support_agent(user)


def can_assign_ticket(user: Any) -> bool:
    return is_support_agent(user)


def can_change_category_or_priority(user: Any) -> bool:
    return is_support_agent(user)


def can_modify_ticket_fields(user: Any, ticket: SupportTicket) -> bool:
    if is_support_agent(user):
        return True
    if ticket.requester_id == user.pk and ticket.status.system_state == SystemState.OPEN.value:
        return True
    return False


def can_transition_ticket(
    user: Any,
    ticket: SupportTicket,
    transition: SupportStatusTransition,
) -> bool:
    role = resolve_support_role(user)
    if not role:
        return False

    allowed_roles = transition.allowed_roles or []
    # If role not explicitly allowed
    if role.value not in allowed_roles:
        return False

    # Check reopening restrictions for requesters
    if transition.to_status.system_state == SystemState.OPEN.value and ticket.status.system_state == SystemState.DONE.value:
        if role == SupportRole.REQUESTER:
            if ticket.requester_id != user.pk:
                return False
            # Check reopen window
            settings = SupportSettings.get_solo()
            resolved_time = ticket.resolved_at or ticket.closed_at or ticket.updated_at
            if timezone.now() > resolved_time + timedelta(days=settings.reopen_window_days):
                return False

    return True


def can_add_comment(user: Any, ticket: SupportTicket, visibility: str) -> bool:
    role = resolve_support_role(user)
    if not role:
        return False
    if visibility == CommentVisibility.INTERNAL.value:
        return role in (SupportRole.AGENT, SupportRole.ADMIN)
    if role in (SupportRole.AGENT, SupportRole.ADMIN):
        return True
    return ticket.requester_id == user.pk


def can_edit_or_delete_comment(user: Any, comment: TicketComment) -> bool:
    if not user or not user.is_authenticated:
        return False
    if comment.author_id != user.pk:
        return False
    if comment.deleted_at is not None:
        return False

    settings = SupportSettings.get_solo()
    cutoff = comment.created_at + timedelta(minutes=settings.comment_edit_window_minutes)
    return timezone.now() <= cutoff


def can_link_resource(user: Any, resource_type: str, resource_id: str | int) -> bool:
    if is_support_agent(user):
        return True
    adapter = get_adapter(resource_type)
    return adapter.can_view(resource_id, user)


def can_unlink_resource(user: Any) -> bool:
    return is_support_agent(user)


def can_manage_configuration(user: Any) -> bool:
    return is_support_admin(user)
