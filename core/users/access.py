"""Labs access control: role vocabulary, role resolution, and permission classes.

``core.users`` owns the role mapping. Each ``URSGroup`` row links a synced URS group to a Django
``Group`` and carries a ``labs_role`` (``admin``, ``coord``, ``user``, or empty), edited by
administrators in Django admin. A user's roles are the ``labs_role`` values of the URS groups whose
Django group they belong to.

* ``admin``: everything a coordinator can do, plus the user directory (groups and members).
* ``coord``: operational management of labs, equipment, licenses, benches, rooms and monitoring;
  procurement, expenses and finance reports; and the work of other users (booking approval).
* ``user``: reads the dashboard (including bench detail) and the leaderboard; creates and changes only
  their own bookings. No direct access to benches, equipment or other Labs data.

The per-endpoint matrix lives in ``core/labs/features/base/access.py`` (owner decision 2026-11-11).

Higher roles imply lower ones (``admin`` > ``coord`` > ``user``). Superusers hold every role. A user
with no mapped group holds no role and can neither read nor write through these classes (fail closed).

Effective roles are cached on the user instance, so a request pays for at most one query. Code that
changes a user's groups and then re-checks access on the same instance must call
``clear_labs_roles_cache`` first.

The generic mechanics live in ``core.common.api.permissions``; this module only supplies the Labs
vocabulary and lookup. Object-level rules (such as booking ownership) are enforced in the
application layer, and querysets must still be scoped by the caller.
"""

from enum import StrEnum
from typing import Any

from django.db.models import Q, QuerySet

from core.common.api.permissions import RoleHierarchy, RolePermission, is_authenticated
from core.users.models import URSGroup, User

_ROLES_CACHE_ATTR = "_labs_roles_cache"


class LabsRole(StrEnum):
    """Labs roles. Values are persisted in ``URSGroup.labs_role`` and must not change."""

    ADMIN = "admin"
    COORDINATOR = "coord"
    USER = "user"


LABS_ROLE_HIERARCHY = RoleHierarchy(
    grants={
        LabsRole.ADMIN: (LabsRole.COORDINATOR, LabsRole.USER),
        LabsRole.COORDINATOR: (LabsRole.USER,),
        LabsRole.USER: (),
    }
)


def effective_labs_roles(user: Any) -> frozenset[str]:
    """Return the Labs roles ``user`` holds, including implied roles.

    Anonymous and missing users hold none; superusers hold all. The result is cached on ``user``.
    """
    if not is_authenticated(user):
        return frozenset()
    if user.is_superuser:
        return LABS_ROLE_HIERARCHY.roles

    cached = getattr(user, _ROLES_CACHE_ATTR, None)
    if cached is not None:
        return cached

    assigned_roles = URSGroup.objects.filter(group__user=user).values_list("labs_role", flat=True).distinct()
    roles = LABS_ROLE_HIERARCHY.expand(assigned_roles)
    setattr(user, _ROLES_CACHE_ATTR, roles)
    return roles


def users_holding_labs_role(role: LabsRole) -> QuerySet[User]:
    """Active users who hold ``role`` directly, through a higher role, or as superusers. One query."""
    granting = [held for held in LABS_ROLE_HIERARCHY.roles if role in LABS_ROLE_HIERARCHY.expand([held])]
    return (
        User.objects.filter(is_active=True)
        .filter(Q(is_superuser=True) | Q(groups__ursgroup__labs_role__in=granting))
        .distinct()
    )


def clear_labs_roles_cache(user: Any) -> None:
    """Drop the cached roles on ``user`` after its groups or role mappings change."""
    if hasattr(user, _ROLES_CACHE_ATTR):
        delattr(user, _ROLES_CACHE_ATTR)


def has_labs_role(user: Any, role: LabsRole) -> bool:
    """Return True when ``user`` holds ``role`` or any role that implies it."""
    return role in effective_labs_roles(user)


class LabsRolePermission(RolePermission):
    """Base for Labs permission classes: roles are resolved from URS group mappings.

    Reads require at least the ``user`` role; a user without any Labs role is denied.
    """

    read_roles = (LabsRole.USER,)

    def resolve_roles(self, user: Any) -> frozenset[str]:
        return effective_labs_roles(user)


class IsLabAdmin(LabsRolePermission):
    """Reads: any Labs role. Writes: lab administrators."""

    write_roles = (LabsRole.ADMIN,)


class IsLabCoordinator(LabsRolePermission):
    """Reads: any Labs role. Writes: lab coordinators and administrators."""

    write_roles = (LabsRole.COORDINATOR,)


class IsLabMember(LabsRolePermission):
    """Reads and writes: any Labs role. Ownership is enforced per object."""

    write_roles = (LabsRole.USER,)


class IsLabMemberReadOnly(LabsRolePermission):
    """Reads: any Labs role. Writes: nobody (dashboards and rankings)."""

    write_roles = ()


class IsLabCoordinatorReadWrite(LabsRolePermission):
    """Reads and writes: lab coordinators and administrators (procurement, expenses, finance reports)."""

    read_roles = (LabsRole.COORDINATOR,)
    write_roles = (LabsRole.COORDINATOR,)


# Same policy, earlier name used by the equipment feature.
IsLabCoordinatorOnly = IsLabCoordinatorReadWrite


class IsLabAdminReadWrite(LabsRolePermission):
    """Reads and writes: lab administrators only (user directory and group membership)."""

    read_roles = (LabsRole.ADMIN,)
    write_roles = (LabsRole.ADMIN,)


__all__ = [
    "LABS_ROLE_HIERARCHY",
    "IsLabAdmin",
    "IsLabAdminReadWrite",
    "IsLabCoordinator",
    "IsLabCoordinatorReadWrite",
    "IsLabCoordinatorOnly",
    "IsLabMember",
    "IsLabMemberReadOnly",
    "LabsRole",
    "LabsRolePermission",
    "clear_labs_roles_cache",
    "effective_labs_roles",
    "has_labs_role",
    "users_holding_labs_role",
]
