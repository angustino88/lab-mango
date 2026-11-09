"""Add / remove ticket watchers."""

from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction

from core.support_desk.contracts import ActivityEventType
from core.support_desk.exceptions import PermissionDeniedError, RecordNotFoundError
from core.support_desk.features.tickets.application.policies import can_manage_watchers
from core.support_desk.features.tickets.application.shared import actor_display_name, get_ticket_for_actor
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.watcher import TicketWatcher

User = get_user_model()


@dataclass(frozen=True, slots=True)
class WatcherInput:
    ticket_key: str
    user_id: int | None = None  # None -> the actor themself


def add_watcher(command: WatcherInput, *, actor: Any) -> TicketWatcher:
    ticket = get_ticket_for_actor(command.ticket_key, actor)
    target_id = command.user_id or actor.pk
    if not can_manage_watchers(actor, ticket, target_id):
        raise PermissionDeniedError("You can only manage your own subscription to this ticket.")
    target = User.objects.filter(pk=target_id, is_active=True).first()
    if not target:
        raise RecordNotFoundError(f"User {target_id} not found.")

    with transaction.atomic():
        watcher, created = TicketWatcher.objects.get_or_create(ticket=ticket, user=target, defaults={"added_by": actor})
        if created:
            TicketActivity.objects.create(
                ticket=ticket,
                event_type=ActivityEventType.WATCHER_ADDED.value,
                actor=actor,
                actor_name=actor_display_name(actor),
                payload={"user_id": target.pk, "user_name": actor_display_name(target)},
            )
    return watcher


def remove_watcher(command: WatcherInput, *, actor: Any) -> None:
    ticket = get_ticket_for_actor(command.ticket_key, actor)
    target_id = command.user_id or actor.pk
    if not can_manage_watchers(actor, ticket, target_id):
        raise PermissionDeniedError("You can only manage your own subscription to this ticket.")

    with transaction.atomic():
        watcher = TicketWatcher.objects.select_related("user").filter(ticket=ticket, user_id=target_id).first()
        if watcher is None:
            return  # idempotent
        user_name = actor_display_name(watcher.user)
        watcher.delete()
        TicketActivity.objects.create(
            ticket=ticket,
            event_type=ActivityEventType.WATCHER_REMOVED.value,
            actor=actor,
            actor_name=actor_display_name(actor),
            payload={"user_id": target_id, "user_name": user_name},
        )
