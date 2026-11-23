"""Labs access control: resolve what a user may do, and the endpoint policy that checks it.

Design: ``docs/proposals/role-based-access-redesign.md``. Three layers, each with one owner:

* **Role** (``core.users.roles``): who a person is. Assigned through their URS group
  (``URSGroup.labs_role``, edited by superusers in Django admin). A user's roles are the ``labs_role``
  values of the URS groups whose Django group they belong to, plus the roles those imply.
* **Permission** (``core.users.permissions``): what can be done. ``ROLE_PERMISSIONS`` maps roles to
  permissions; it is the access matrix.
* **Check** (this module): features call ``has_permission`` and endpoints declare a
  ``LabsAccessPolicy``. Nothing outside ``core.users`` checks a role
  (``tests/architecture/test_users_feature_boundaries.py``).

Deny by default: anonymous users, API keys, users without a mapped group and unknown permissions hold
nothing (inactive users cannot sign in). Superusers (platform owners) hold every permission. Django
``is_staff`` only opens the Django admin site and grants no Labs permission.

Roles are read from the database once per request and cached on the user instance. Code that changes a
user's groups and then re-checks access on the same instance must call ``clear_labs_roles_cache`` first.
Object-level rules (such as booking ownership) are enforced in the application layer, and querysets must
still be scoped by the caller.
"""

from typing import Any, cast

from django.conf import settings
from django.db.models import Q, QuerySet

from core.common.api.permissions import CapabilityPermission, is_authenticated
from core.common.cache import get_namespace_version, safe_cache_delete, safe_cache_get, safe_cache_set
from core.common.domain.errors import Forbidden
from core.users.models import URSGroup, User
from core.users.permissions import ALL_PERMISSIONS, LabsPermission, permissions_for_roles, roles_granting
from core.users.roles import LabsRole

_ROLES_CACHE_ATTR = "_labs_roles_cache"
_VALID_ROLES = frozenset(LabsRole.values)
USERS_ACCESS_CACHE_NAMESPACE = "users:access"


def _roles_cache_key(user_id: Any, version: int) -> str:
    return f"users:labs_roles:v{version}:{user_id}"


def effective_labs_roles(user: Any) -> frozenset[str]:
    """The Labs roles assigned to ``user`` through URS groups (or ``admin`` for superusers).

    Hierarchy expansion happens in ``permissions_for_roles`` when computing ``effective_permissions``, so an
    administrator's ``effective_roles.labs`` lists ``["admin"]`` while their ``effective_permissions.labs``
    includes every permission granted by ``admin``, ``coord`` and ``member``.
    """
    if not is_authenticated(user):
        return frozenset()
    if user.is_superuser:
        return frozenset({LabsRole.ADMIN.value})

    cached = getattr(user, _ROLES_CACHE_ATTR, None)
    if cached is not None:
        return cached

    cache_enabled = bool(getattr(settings, "API_AUTH_CACHE_ENABLED", False))
    cache_key: str | None = None
    if cache_enabled and getattr(user, "pk", None) is not None:
        ns_ver = get_namespace_version(USERS_ACCESS_CACHE_NAMESPACE)
        if ns_ver > 0:
            cache_key = _roles_cache_key(user.pk, ns_ver)
            cached_roles = safe_cache_get(cache_key)
            if cached_roles is not None:
                roles = frozenset(role for role in cached_roles if role in _VALID_ROLES)
                setattr(user, _ROLES_CACHE_ATTR, roles)
                return roles

    assigned_roles = URSGroup.objects.filter(group__user=user).values_list("labs_role", flat=True).distinct()
    roles = frozenset(role for role in assigned_roles if role in _VALID_ROLES)
    setattr(user, _ROLES_CACHE_ATTR, roles)
    if cache_key is not None:
        ttl = int(getattr(settings, "API_AUTH_CACHE_TTL", 120) or 120)
        safe_cache_set(cache_key, tuple(sorted(roles)), timeout=ttl)
    return roles


def effective_permissions(user: Any) -> frozenset[str]:
    """Every Labs permission ``user`` holds (at most one query per request, shared with the roles)."""
    if is_authenticated(user) and user.is_superuser:
        return ALL_PERMISSIONS
    return permissions_for_roles(effective_labs_roles(user))


def has_permission(user: Any, permission: LabsPermission) -> bool:
    """Whether ``user`` holds ``permission``. API keys and anonymous users hold none."""
    return permission in effective_permissions(user)


def require_permission(user: Any, permission: LabsPermission, *, message: str | None = None) -> None:
    """Raise ``Forbidden`` (code ``permission_denied``) unless ``user`` holds ``permission``.

    Features that already publish a specific error code keep raising their own error after ``has_permission``.
    """
    if not has_permission(user, permission):
        raise Forbidden(message)


def is_lab_operator(user: Any) -> bool:
    """Whether ``user`` is a lab operator (holds lab operations authority). For wording, not for rules."""
    return has_permission(user, LabsPermission.LAB_OPERATIONS_MANAGE)


def users_with_permission(permission: LabsPermission) -> QuerySet[User]:
    """Active users who hold ``permission`` through a role, or as superusers. One query; usable as a subquery."""
    granting = roles_granting(permission)
    return (
        User.objects.filter(is_active=True)
        .filter(Q(is_superuser=True) | Q(groups__ursgroup__labs_role__in=granting))
        .distinct()
    )


def clear_labs_roles_cache(user: Any) -> None:
    """Drop the cached roles on ``user`` after its groups or role mappings change."""
    if hasattr(user, _ROLES_CACHE_ATTR):
        delattr(user, _ROLES_CACHE_ATTR)
    if getattr(settings, "API_AUTH_CACHE_ENABLED", False) and getattr(user, "pk", None) is not None:
        ns_ver = get_namespace_version(USERS_ACCESS_CACHE_NAMESPACE)
        if ns_ver > 0:
            safe_cache_delete(_roles_cache_key(user.pk, ns_ver))


class LabsAccessPolicy(CapabilityPermission):
    """DRF permission for Labs endpoints: one permission for reads, one for writes (``None`` denies).

    Create policies with ``LabsAccessPolicy.of`` and name them after what they protect; compose with
    ``HasAPIKeyAccess`` (``HasAPIKeyAccess | policy``) only where machine clients are allowed.
    """

    def resolve_capabilities(self, user: Any) -> frozenset[str]:
        return effective_permissions(user)

    @classmethod
    def of(
        cls,
        name: str,
        *,
        read: LabsPermission | None,
        write: LabsPermission | None,
    ) -> type["LabsAccessPolicy"]:
        policy = cast(type[LabsAccessPolicy], cls.requiring(read=read, write=write, name=name))
        policy.__doc__ = f"Reads: {read.value if read else 'nobody'}. Writes: {write.value if write else 'nobody'}."
        return policy


__all__ = [
    "LabsAccessPolicy",
    "LabsPermission",
    "clear_labs_roles_cache",
    "effective_labs_roles",
    "effective_permissions",
    "has_permission",
    "is_lab_operator",
    "require_permission",
    "users_with_permission",
]
