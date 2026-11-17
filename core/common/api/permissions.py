"""Generic, role-based permission building blocks.

This module is business-agnostic technical code. It knows nothing about Labs, URS groups, or any
concrete role names, and must not import business apps. Applications supply the role vocabulary
and the lookup, then reuse the pieces here:

* ``RoleHierarchy``: declares which roles imply others (for example admin implies manager).
* ``RolePermission``: a DRF permission that gates requests by role and HTTP method class.
* ``is_owner``: object-level ownership check against a user-stamped field.
* ``HasAPIKeyAccess``: API-key access that can be switched off with ``API_KEY_ACCESS_ENABLED``.

Authorization stays deny-by-default: unauthenticated callers are always rejected, and unsafe
methods require a role unless a subclass explicitly says otherwise. Object-level rules are
enforced in the application layer, and querysets must still be scoped by the caller.
"""

from collections.abc import Collection, Iterable, Mapping, Set
from dataclasses import dataclass, field
from typing import Any, ClassVar

from django.conf import settings
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey


def is_authenticated(user: Any) -> bool:
    """Return True for a real, authenticated user. ``None`` and anonymous users are not."""
    return bool(user and user.is_authenticated)


@dataclass(frozen=True, slots=True)
class RoleHierarchy:
    """Declares which roles each role grants, so holding a higher role implies the lower ones.

    ``grants`` maps a role to the roles it implies. A role always includes itself.
    """

    grants: Mapping[str, Collection[str]] = field(default_factory=dict)

    @property
    def roles(self) -> frozenset[str]:
        """Every role known to the hierarchy."""
        known = set(self.grants)
        for implied in self.grants.values():
            known.update(implied)
        return frozenset(known)

    def expand(self, assigned_roles: Iterable[str]) -> frozenset[str]:
        """Return ``assigned_roles`` plus every role they imply. Unknown roles are dropped."""
        known = self.roles
        effective: set[str] = set()
        for role in assigned_roles:
            if role not in known:
                continue
            effective.add(role)
            effective.update(self.grants.get(role, ()))
        return frozenset(effective)


class RolePermission(BasePermission):
    """Gate requests by role. Subclass, set the roles, and implement ``resolve_roles``.

    * Safe methods: any authenticated user when ``read_roles`` is ``None``; otherwise a user
      holding at least one of ``read_roles``.
    * Unsafe methods: a user holding at least one of ``write_roles``. Leaving ``write_roles``
      empty denies every write.
    """

    read_roles: ClassVar[Collection[str] | None] = None
    write_roles: ClassVar[Collection[str]] = ()
    message = "You do not have permission to perform this action."

    def resolve_roles(self, user: Any) -> Set[str]:
        """Return the effective roles of an authenticated ``user`` (implied roles included)."""
        raise NotImplementedError(f"{type(self).__name__} must implement resolve_roles().")

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = getattr(request, "user", None)
        if not is_authenticated(user):
            return False
        required = self.read_roles if request.method in SAFE_METHODS else self.write_roles
        if required is None:
            return True
        return not self.resolve_roles(user).isdisjoint(required)


def api_key_access_enabled() -> bool:
    """True unless ``settings.API_KEY_ACCESS_ENABLED`` is set to False (default: enabled)."""
    return bool(getattr(settings, "API_KEY_ACCESS_ENABLED", True))


class HasAPIKeyAccess(HasAPIKey):
    """A valid API key grants access only while API-key access is enabled.

    Use this instead of ``rest_framework_api_key.permissions.HasAPIKey`` so one setting turns every
    API-key path on or off.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        return api_key_access_enabled() and super().has_permission(request, view)

    def has_object_permission(self, request: Request, view: APIView, obj: Any) -> bool:
        return api_key_access_enabled() and super().has_object_permission(request, view, obj)


def is_owner(user: Any, obj: Any, *, owner_field: str = "creator_id") -> bool:
    """Return True when ``obj`` was created by ``user`` (compares ``obj.<owner_field>`` to ``user.pk``)."""
    if not is_authenticated(user):
        return False
    owner_id = getattr(obj, owner_field, None)
    return owner_id is not None and owner_id == user.pk


__all__ = [
    "HasAPIKeyAccess",
    "RoleHierarchy",
    "RolePermission",
    "api_key_access_enabled",
    "is_authenticated",
    "is_owner",
]
