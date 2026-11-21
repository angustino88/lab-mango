"""Lifecycle commands for local stub identities (``tools/stubs``); local development and tests only.

Design: ``docs/proposals/local-identity-stubs.md``. Every function refuses unless the stub issuer is on, in
DEBUG, not SSO-only, for the reserved stub tenant (the ``users.E014`` conditions), and the target is a stub
user: username prefix ``stub.``, not URS-managed and, when bound, bound in the stub tenant. A copied
database's real users are therefore never read for change, changed or deleted.

Writes go through the lifecycle commands with the caller ``stub-identities-command``, so routing
publication and the audit trail are the same as on production paths. Stub roles use URS groups with
reserved ids and ``active=False``: the scheduled URS sync fetches only active groups
(``core/users/tasks.py``) and reconciles only URS-managed users, so it never touches them.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import transaction

from core.users.features.lifecycle.application import (
    bind_entra_identity,
    delete_user,
    replace_entra_identity,
    set_user_active,
    unlink_entra_identity,
)
from core.users.features.lifecycle.contracts import (
    BindEntraIdentityInput,
    DeleteUserInput,
    ReplaceEntraIdentityInput,
    SetUserActiveInput,
    UnlinkEntraIdentityInput,
    UserLifecycleResult,
)
from core.users.models import EntraIdentity, URSGroup, User

STUB_CALLER = "stub-identities-command"
STUB_USERNAME_PREFIX = "stub."
# Reserved URS group ids for stub roles; real URS ids are far smaller.
STUB_URS_GROUP_IDS = {"admin": 9_000_000_000_001, "coord": 9_000_000_000_002, "member": 9_000_000_000_003}


class StubIdentitiesDisabled(PermissionError):
    """Stub identities are not allowed in this configuration, or the target is not a stub user."""


@dataclass(frozen=True, slots=True)
class StubUserInput:
    username: str
    name: str
    email: str
    labs_role: str = ""  # "", "member", "coord" or "admin"


@dataclass(frozen=True, slots=True)
class StubUserResult:
    user_id: int
    changed: bool


@dataclass(frozen=True, slots=True)
class StubUserState:
    user_id: int
    username: str
    is_active: bool
    labs_roles: tuple[str, ...]
    tenant_id: UUID | None
    object_id: UUID | None


def stub_tenant_id() -> UUID:
    """The configured stub tenant, after checking that stub identities are allowed here."""
    tenant = UUID(str(settings.ENTRA_STUB_TENANT_ID))
    if not (
        getattr(settings, "ENTRA_STUB_ISSUER_ENABLED", False)
        and settings.DEBUG
        and not settings.ENTRA_SSO_ONLY
        and UUID(str(settings.AAD_TENANT_ID)) == tenant
    ):
        raise StubIdentitiesDisabled(
            "Stub identities need ENTRA_STUB_ISSUER_ENABLED, DEBUG, and AAD_TENANT_ID = ENTRA_STUB_TENANT_ID."
        )
    return tenant


def ensure_stub_user(data: StubUserInput) -> StubUserResult:
    """Create or update a stub user and its stub role group membership. Safe to run twice.

    Race guard: the unique username (``get_or_create`` re-reads on conflict), then the user row lock.
    Only stub role groups are added or removed; other group memberships are left alone.
    """
    stub_tenant_id()
    _require_stub_username(data.username)
    if data.labs_role not in {"", *STUB_URS_GROUP_IDS}:
        raise ValueError(f"Unknown labs role {data.labs_role!r}.")
    wanted_group = _ensure_stub_role_group(data.labs_role) if data.labs_role else None
    with transaction.atomic():
        user, created = User.objects.get_or_create(
            username=data.username,
            defaults={"name": data.name, "email": data.email, "is_urs_managed": False},
        )
        user = User.objects.select_for_update().get(pk=user.pk)
        if user.is_urs_managed:
            raise StubIdentitiesDisabled(f"{data.username} is URS-managed, so it is not a stub user.")
        changed = created
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
        updates = [field for field in ("name", "email") if getattr(user, field) != getattr(data, field)]
        if updates:
            for field in updates:
                setattr(user, field, getattr(data, field))
            user.save(update_fields=updates)
            changed = True
        stub_groups = set(
            URSGroup.objects.filter(urs_group_id__in=STUB_URS_GROUP_IDS.values(), group__isnull=False).values_list(
                "group_id", flat=True
            )
        )
        current = set(user.groups.filter(pk__in=stub_groups).values_list("pk", flat=True))
        wanted = {wanted_group.pk} if wanted_group is not None else set()
        if current != wanted:
            user.groups.remove(*(current - wanted))
            user.groups.add(*(wanted - current))
            changed = True
        return StubUserResult(user_id=user.pk, changed=changed)


def stub_bind_entra_identity(*, user_id: int, object_id: UUID) -> UserLifecycleResult:
    tenant = _require_stub_user(user_id)
    return bind_entra_identity(
        caller=STUB_CALLER, data=BindEntraIdentityInput(user_id=user_id, tenant_id=tenant, object_id=object_id)
    )


def stub_replace_entra_identity(*, user_id: int, object_id: UUID) -> UserLifecycleResult:
    tenant = _require_stub_user(user_id)
    return replace_entra_identity(
        caller=STUB_CALLER, data=ReplaceEntraIdentityInput(user_id=user_id, tenant_id=tenant, object_id=object_id)
    )


def stub_unlink_entra_identity(*, user_id: int) -> UserLifecycleResult:
    _require_stub_user(user_id)
    return unlink_entra_identity(caller=STUB_CALLER, data=UnlinkEntraIdentityInput(user_id=user_id))


def stub_set_user_active(*, user_id: int, is_active: bool) -> UserLifecycleResult:
    _require_stub_user(user_id)
    return set_user_active(caller=STUB_CALLER, data=SetUserActiveInput(user_id=user_id, is_active=is_active))


def stub_delete_user(*, user_id: int) -> UserLifecycleResult:
    _require_stub_user(user_id)
    return delete_user(caller=STUB_CALLER, data=DeleteUserInput(user_id=user_id))


def list_stub_users() -> list[StubUserState]:
    """Every stub user with its activity, stub roles and binding. Three queries."""
    stub_tenant_id()
    users = list(
        User.objects.filter(username__startswith=STUB_USERNAME_PREFIX, is_urs_managed=False)
        .order_by("username")
        .values_list("pk", "username", "is_active")
    )
    ids = [row[0] for row in users]
    identities = {
        row[0]: (row[1], row[2])
        for row in EntraIdentity.objects.filter(user_id__in=ids).values_list("user_id", "tenant_id", "object_id")
    }
    roles: dict[int, set[str]] = {}
    for user_pk, role in URSGroup.objects.filter(
        urs_group_id__in=STUB_URS_GROUP_IDS.values(), group__user__in=ids
    ).values_list("group__user", "labs_role"):
        roles.setdefault(user_pk, set()).add(role)
    return [
        StubUserState(
            user_id=pk,
            username=username,
            is_active=is_active,
            labs_roles=tuple(sorted(roles.get(pk, ()))),
            tenant_id=identities.get(pk, (None, None))[0],
            object_id=identities.get(pk, (None, None))[1],
        )
        for pk, username, is_active in users
    ]


def _ensure_stub_role_group(labs_role: str) -> Group:
    """The inactive URS group (reserved id) and Django group that grant ``labs_role``. Safe to run twice."""
    with transaction.atomic():
        urs_group, _ = URSGroup.objects.get_or_create(
            urs_group_id=STUB_URS_GROUP_IDS[labs_role],
            defaults={"urs_group_name": f"stub-{labs_role}", "active": False, "labs_role": labs_role},
        )
        # Linked here rather than through urs_sync (capabilities do not import each other). The OneToOne
        # on URSGroup.group makes a name clash with a group owned by a real URS row fail loudly.
        group, _ = Group.objects.get_or_create(name=f"stub-{labs_role}")
        if urs_group.active or urs_group.labs_role != labs_role or urs_group.group_id != group.pk:
            URSGroup.objects.filter(pk=urs_group.pk).update(active=False, labs_role=labs_role, group=group)
    return group


def _require_stub_username(username: str) -> None:
    if not username.startswith(STUB_USERNAME_PREFIX) or len(username) <= len(STUB_USERNAME_PREFIX):
        raise StubIdentitiesDisabled(f"Stub usernames start with {STUB_USERNAME_PREFIX!r}.")


def _require_stub_user(user_id: int) -> UUID:
    tenant = stub_tenant_id()
    user = User.objects.filter(pk=user_id).values_list("username", "is_urs_managed").first()
    if user is None:
        raise User.DoesNotExist(f"User {user_id} does not exist.")
    _require_stub_username(user[0])
    if user[1]:
        raise StubIdentitiesDisabled(f"{user[0]} is URS-managed, so it is not a stub user.")
    bound_tenant = EntraIdentity.objects.filter(user_id=user_id).values_list("tenant_id", flat=True).first()
    if bound_tenant is not None and bound_tenant != tenant:
        raise StubIdentitiesDisabled(f"{user[0]} is bound in another tenant, so it is not a stub user.")
    return tenant
