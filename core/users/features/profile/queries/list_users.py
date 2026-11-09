"""Query: list and fetch users, scoped to what the actor may see. Read-only."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import QuerySet

from core.users.features.profile.contracts import ActorContext

User = get_user_model()


def visible_users_for(*, actor: ActorContext, is_staff: bool, is_api_client: bool = False) -> QuerySet:
    """Return users the actor may see.

    Staff and trusted API-key clients see all users. Other authenticated users see only themselves.
    """
    queryset = User.objects.all().order_by("pk")
    if is_staff or is_api_client:
        return queryset
    return queryset.filter(pk=actor.user_id)


def get_visible_user(*, actor: ActorContext, is_staff: bool, pk: int, is_api_client: bool = False):
    """Return a single visible user, or None when outside the actor's scope."""
    return visible_users_for(actor=actor, is_staff=is_staff, is_api_client=is_api_client).filter(pk=pk).first()
