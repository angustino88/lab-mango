"""Command: update a user's editable profile fields. Authorization checked by caller scope."""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction

from core.users.features.profile.contracts import ActorContext
from core.users.features.profile.exceptions import UserNotFound

EDITABLE_FIELDS = ("display_name", "name", "department")


@dataclass(frozen=True)
class UpdateUserInput:
    values: dict


def update_user(*, actor: ActorContext, target_pk: int, data: UpdateUserInput, is_staff: bool, is_api_client: bool = False):
    """Apply allowed field updates. Non-staff may only update themselves."""
    user_model = get_user_model()
    if not (is_staff or is_api_client or target_pk == actor.user_id):
        raise UserNotFound()
    allowed = {k: v for k, v in data.values.items() if k in EDITABLE_FIELDS}
    with transaction.atomic():
        try:
            user = user_model.objects.select_for_update().get(pk=target_pk)
        except user_model.DoesNotExist as exc:
            raise UserNotFound() from exc
        for field, value in allowed.items():
            setattr(user, field, value)
        user.save(update_fields=list(allowed) or None)
    return user
