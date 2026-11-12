"""The public surface of ``core.users`` for other apps.

Other apps import roles, permission classes and user lifecycle contracts from here, never from
``core.users.access`` or ``core.users.features``. These wrappers are internal APIs, not a security
boundary against arbitrary code already executing in this Django process.
"""

from dataclasses import dataclass
from uuid import UUID

from core.users.access import (
    IsLabAdmin,
    IsLabAdminReadWrite,
    IsLabCoordinator,
    IsLabCoordinatorOnly,
    IsLabCoordinatorReadWrite,
    IsLabMember,
    IsLabMemberReadOnly,
    LabsRole,
    clear_labs_roles_cache,
    effective_labs_roles,
    has_labs_role,
    users_holding_labs_role,
)
from core.users.features.auth.access_token import with_entra_access_token
from core.users.features.lifecycle.application import (
    _bind_entra_identity_from_operator,
    _delete_user_from_operator,
    _replace_entra_identity_from_operator,
    _unlink_entra_identity_from_operator,
)
from core.users.features.lifecycle.public import (
    BindEntraIdentityInput,
    DeleteUserInput,
    ReplaceEntraIdentityInput,
    SetUserActiveInput,
    UnlinkEntraIdentityInput,
    UserLifecycleResult,
    has_ever_been_bound,
)
from core.users.features.lifecycle.public import (
    bind_entra_identity as _bind_entra_identity,
)
from core.users.features.lifecycle.public import (
    set_user_active as _set_user_active,
)
from core.users.features.urs_sync.mapping import ensure_linked_group as _ensure_linked_group
from core.users.models import EntraIdentity, User


@dataclass(frozen=True, slots=True)
class VerifiedTeamsRecipient:
    tenant_id: UUID
    object_id: UUID


@dataclass(frozen=True, slots=True)
class NotificationRecipientProfile:
    user_id: int
    username: str
    email: str
    is_active: bool
    teams_recipient: VerifiedTeamsRecipient | None = None


def bind_entra_identity(*, data: BindEntraIdentityInput) -> UserLifecycleResult:
    """Bind an identity for the trusted first-login workflow (internal provenance convention)."""
    return _bind_entra_identity(caller="aad-login", data=data)


def bind_entra_identity_from_operator(*, data: BindEntraIdentityInput) -> UserLifecycleResult:
    """Bind an identity for the trusted operator management-command workflow."""
    return _bind_entra_identity_from_operator(data=data)


def set_user_active(*, data: SetUserActiveInput) -> UserLifecycleResult:
    """Set activity from the trusted URS sync workflow (internal provenance convention)."""
    return _set_user_active(caller="urs-sync", data=data)


def replace_entra_identity(*, data: ReplaceEntraIdentityInput) -> UserLifecycleResult:
    return _replace_entra_identity_from_operator(data)


def unlink_entra_identity(*, data: UnlinkEntraIdentityInput) -> UserLifecycleResult:
    return _unlink_entra_identity_from_operator(data)


def delete_user(*, data: DeleteUserInput) -> UserLifecycleResult:
    return _delete_user_from_operator(data)


def ensure_urs_group_linked(*, urs_group_id: int) -> int:
    """Create or rename the Django group of URS group row ``urs_group_id``; return the Django group id."""
    return _ensure_linked_group(urs_group_id).pk


def resolve_teams_recipient(*, user_id: int, expected_tenant_id: UUID | None) -> VerifiedTeamsRecipient | None:
    """Use only the existing administratively provisioned binding, never email."""
    if expected_tenant_id is None:
        return None
    identity = (
        EntraIdentity.objects.filter(
            user_id=user_id,
            user__is_active=True,
            tenant_id=expected_tenant_id,
        )
        .values("tenant_id", "object_id")
        .first()
    )
    if identity is None or identity["tenant_id"] != expected_tenant_id:
        return None
    return VerifiedTeamsRecipient(tenant_id=identity["tenant_id"], object_id=identity["object_id"])


def resolve_notification_recipient(
    *,
    user_id: int,
    expected_teams_tenant_id: UUID | None = None,
) -> NotificationRecipientProfile | None:
    """Resolve an active user's notification profile and optional Teams identity."""
    user = User.objects.filter(pk=user_id).values("pk", "username", "email", "is_active").first()
    if user is None:
        return None
    teams_recipient = (
        resolve_teams_recipient(user_id=user_id, expected_tenant_id=expected_teams_tenant_id)
        if expected_teams_tenant_id
        else None
    )
    return NotificationRecipientProfile(
        user_id=user["pk"],
        username=user["username"],
        email=user["email"] or "",
        is_active=user["is_active"],
        teams_recipient=teams_recipient,
    )


def resolve_user_id_for_login_name(*, login_name: str | None) -> int | None:
    """The active user whose username is this login name, or None (owner decision O23).

    Case is ignored and a Windows ``DOMAIN\\`` prefix is dropped. No match, or more than one user
    differing only by case, returns None: a session is never attributed to a guessed person.
    """
    name = (login_name or "").strip().rsplit("\\", 1)[-1].strip()
    if not name:
        return None
    matches = list(User.objects.filter(username__iexact=name, is_active=True).values_list("pk", flat=True)[:2])
    return matches[0] if len(matches) == 1 else None


__all__ = [
    "BindEntraIdentityInput",
    "DeleteUserInput",
    "ReplaceEntraIdentityInput",
    "SetUserActiveInput",
    "UnlinkEntraIdentityInput",
    "IsLabAdmin",
    "IsLabAdminReadWrite",
    "IsLabCoordinator",
    "IsLabCoordinatorReadWrite",
    "IsLabCoordinatorOnly",
    "IsLabMember",
    "IsLabMemberReadOnly",
    "LabsRole",
    "NotificationRecipientProfile",
    "VerifiedTeamsRecipient",
    "UserLifecycleResult",
    "bind_entra_identity",
    "bind_entra_identity_from_operator",
    "delete_user",
    "ensure_urs_group_linked",
    "has_ever_been_bound",
    "replace_entra_identity",
    "set_user_active",
    "unlink_entra_identity",
    "clear_labs_roles_cache",
    "effective_labs_roles",
    "has_labs_role",
    "resolve_notification_recipient",
    "resolve_user_id_for_login_name",
    "resolve_teams_recipient",
    "users_holding_labs_role",
    "with_entra_access_token",
]
