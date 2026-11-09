"""Command: upload or replace the actor's own avatar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction

from core.users.features.profile.contracts import ActorContext
from core.users.features.profile.exceptions import AvatarInvalid

MAX_AVATAR_BYTES = 5 * 1024 * 1024
ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})


@dataclass(frozen=True)
class UploadAvatarInput:
    image: Any


def upload_avatar(*, actor: ActorContext, data: UploadAvatarInput):
    """Validate and store the avatar for the actor. Returns the updated user."""
    user_model = get_user_model()
    image = data.image
    size = getattr(image, "size", 0)
    if size > MAX_AVATAR_BYTES:
        raise AvatarInvalid({"avatar": ["Avatar file size must not exceed 5 MB."]})
    content_type = getattr(image, "content_type", None)
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        raise AvatarInvalid({"avatar": ["Unsupported image type."]})

    with transaction.atomic():
        user = user_model.objects.select_for_update().get(pk=actor.user_id)
        if user.avatar and user.avatar.storage.exists(user.avatar.name):
            user.avatar.storage.delete(user.avatar.name)
        user.avatar = image
        user.save(update_fields=["avatar"])
    return user
