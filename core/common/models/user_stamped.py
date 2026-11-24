"""Abstract model recording who created and who last modified a row."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser


def authenticated_actor(user: Any) -> AbstractBaseUser | None:
    """Return `user` only if it is an authenticated user instance, else None."""
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    return None


class UserStampedModel(models.Model):
    """
    Abstract mixin recording who created and who last modified a row.

    Usage in application commands, tasks and management commands:

        instance.save(actor=user)

    Behavior:
      * `last_modified_by` is set on every save with an authenticated actor.
      * `creator` is set only on insert and only if it is still empty, so
        explicit values (imports, fixtures, admin) are never overwritten.
      * Anonymous or missing actors leave both fields untouched.
      * `update_fields=[]` is respected (Django's "save nothing"); otherwise
        stamped fields are added to `update_fields` automatically.

    Limitations:
      * `bulk_create`, `bulk_update` and `QuerySet.update()` do not call
        `save()`, so they do not stamp users. Set the fields explicitly there.
    """

    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Created by"),
        related_name="%(app_label)s_%(class)s_creator",
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
    )
    last_modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Last modified by"),
        related_name="%(app_label)s_%(class)s_last_modified_by",
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
    )

    class Meta:
        abstract = True

    def save(
        self,
        *args: Any,
        actor: Any = None,
        **kwargs: Any,
    ) -> None:
        user = authenticated_actor(actor)
        update_fields = kwargs.get("update_fields")

        # An explicit empty update_fields means "write nothing"; don't override it.
        if user is not None and (update_fields is None or len(update_fields) > 0):
            stamped = ["last_modified_by"]
            self.last_modified_by = user
            if self._state.adding and self.creator_id is None:
                self.creator = user
                stamped.append("creator")
            if update_fields is not None:
                kwargs["update_fields"] = tuple(dict.fromkeys((*update_fields, *stamped)))

        super().save(*args, **kwargs)
