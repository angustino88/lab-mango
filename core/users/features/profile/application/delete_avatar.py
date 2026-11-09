"""Command: remove the actor's own avatar."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction

from core.users.features.profile.contracts import ActorContext
from core.users.features.profile.exceptions import AvatarNotFound


def delete_avatar(*, actor: ActorContext) -> None:
    """Delete the actor's avatar. Raises AvatarNotFound when none exists."""
    user_model = get_user_model()
    with transaction.atomic():
        user = user_model.objects.select_for_update().get(pk=actor.user_id)
        if not user.avatar:
            raise AvatarNotFound()
        user.avatar.delete(save=True)
