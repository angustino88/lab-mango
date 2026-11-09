"""Query: read the actor's own user record for avatar display. Read-only."""

from __future__ import annotations

from django.contrib.auth import get_user_model

from core.users.features.profile.contracts import ActorContext
from core.users.features.profile.exceptions import AvatarNotFound


def get_avatar_owner(*, actor: ActorContext):
    """Return the actor's user (scoped to the actor). Raises if missing."""
    try:
        return get_user_model().objects.get(pk=actor.user_id)
    except get_user_model().DoesNotExist as exc:
        raise AvatarNotFound() from exc
