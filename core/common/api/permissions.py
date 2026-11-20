"""Generic role-based access control (RBAC) building blocks.

This module is business-agnostic technical code. It knows nothing about Labs, URS groups, or any
concrete role or capability names, and must not import business apps. Applications supply the
vocabulary and the lookup, then reuse the pieces here:

* ``RoleHierarchy``: declares which roles imply others (for example admin implies manager).
* ``CapabilityPermission``: a DRF permission that gates a request on one named capability for reads
  and one for writes. Applications map roles to capabilities; endpoints never name roles.
* ``is_owner``: object-level ownership check against a user-stamped field.
* ``HasAPIKeyAccess``: API-key access that can be switched off with ``API_KEY_ACCESS_ENABLED``.

Authorization is deny-by-default: unauthenticated callers are always rejected, and a method class
without a required capability is denied. Object-level rules are enforced in the application layer,
and querysets must still be scoped by the caller.
"""

from collections.abc import Collection, Iterable, Mapping, Set
from dataclasses import dataclass, field
from typing import Any, ClassVar, TypeAlias

from django.conf import settings
from rest_framework.permissions import SAFE_METHODS, BasePermission, OperandHolder
from rest_framework.request import Request
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey

# What a view assigns to ``permission_classes``: permission classes, or ``|`` compositions of them.
PermissionClasses: TypeAlias = list[type[BasePermission] | OperandHolder]


def is_authenticated(user: Any) -> bool:
    """Return True for a real, authenticated user. ``None``, anonymous users and objects that are not users
    (no ``is_authenticated``) are not: access checks deny instead of failing."""
    return bool(user and getattr(user, "is_authenticated", False))


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


class CapabilityPermission(BasePermission):
    """Gate requests by capability. Subclass, set the capabilities, and implement ``resolve_capabilities``.

    * Safe methods (GET, HEAD, OPTIONS): the user must hold ``read_capability``.
    * Unsafe methods: the user must hold ``write_capability``.
    * A capability left as ``None`` denies that method class (deny-by-default).

    Applications create one subclass per endpoint policy (see ``requiring``); the class name and the
    two capabilities make every policy readable in code, tests and generated documentation.
    """

    read_capability: ClassVar[str | None] = None
    write_capability: ClassVar[str | None] = None
    message = "You do not have permission to perform this action."

    def resolve_capabilities(self, user: Any) -> Set[str]:
        """Return every capability an authenticated ``user`` holds."""
        raise NotImplementedError(f"{type(self).__name__} must implement resolve_capabilities().")

    def required_capability(self, request: Request) -> str | None:
        return self.read_capability if request.method in SAFE_METHODS else self.write_capability

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = getattr(request, "user", None)
        if not is_authenticated(user):
            return False
        required = self.required_capability(request)
        return required is not None and required in self.resolve_capabilities(user)

    @classmethod
    def requiring(cls, *, read: str | None, write: str | None, name: str) -> type["CapabilityPermission"]:
        """A named subclass that requires ``read`` for safe methods and ``write`` for the others."""
        return type(name, (cls,), {"read_capability": read, "write_capability": write, "__module__": cls.__module__})


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
    "CapabilityPermission",
    "HasAPIKeyAccess",
    "PermissionClasses",
    "RoleHierarchy",
    "api_key_access_enabled",
    "is_authenticated",
    "is_owner",
]
