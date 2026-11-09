"""Explicit external exports of the profile feature. Leaf facade; no API imports."""

from core.users.features.profile.application import (
    UpdateUserInput,
    delete_avatar,
    update_user,
    upload_avatar,
)
from core.users.features.profile.contracts import ActorContext, UploadedImage
from core.users.features.profile.exceptions import AvatarInvalid, AvatarNotFound, ProfileError
from core.users.features.profile.queries import get_avatar_owner, get_visible_user

__all__ = [
    "ActorContext",
    "AvatarInvalid",
    "AvatarNotFound",
    "ProfileError",
    "UpdateUserInput",
    "UploadedImage",
    "delete_avatar",
    "get_avatar_owner",
    "get_visible_user",
    "update_user",
    "upload_avatar",
]
