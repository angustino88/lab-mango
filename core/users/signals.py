"""Post-commit cache invalidation for user roles, group memberships, and Entra bindings.

Auto-loaded by ``UsersConfig.ready()`` in ``core/users/apps.py``. Imports only models and
technical cache helpers (no cross-capability feature imports).
"""

from __future__ import annotations

from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from core.common.cache import bump_namespace_version_on_commit
from core.users.access import USERS_ACCESS_CACHE_NAMESPACE
from core.users.models import EntraIdentity, URSGroup, User


def _bump_users_access(**kwargs) -> None:
    bump_namespace_version_on_commit(USERS_ACCESS_CACHE_NAMESPACE)


@receiver(post_save, sender=URSGroup, dispatch_uid="users_cache_inv_ursgroup_save")
@receiver(post_delete, sender=URSGroup, dispatch_uid="users_cache_inv_ursgroup_delete")
def _on_urs_group_change(sender, **kwargs) -> None:
    _bump_users_access()


@receiver(post_save, sender=EntraIdentity, dispatch_uid="users_cache_inv_entra_save")
@receiver(post_delete, sender=EntraIdentity, dispatch_uid="users_cache_inv_entra_delete")
def _on_entra_identity_change(sender, **kwargs) -> None:
    _bump_users_access()


@receiver(post_save, sender=User, dispatch_uid="users_cache_inv_user_save")
@receiver(post_delete, sender=User, dispatch_uid="users_cache_inv_user_delete")
def _on_user_change(sender, **kwargs) -> None:
    _bump_users_access()


@receiver(m2m_changed, sender=User.groups.through, dispatch_uid="users_cache_inv_user_groups_m2m")
def _on_user_groups_change(sender, action: str, **kwargs) -> None:
    if action in {"post_add", "post_remove", "post_clear"}:
        _bump_users_access()
