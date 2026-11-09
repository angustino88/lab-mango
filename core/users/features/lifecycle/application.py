"""Commands that own user activity and Entra identity lifecycle writes."""

from __future__ import annotations

from django.db import IntegrityError, transaction

from core.routing.public import publish_user_identity
from core.users.features.lifecycle.contracts import (
    BindEntraIdentityInput,
    DeleteUserInput,
    ReplaceEntraIdentityInput,
    SetUserActiveInput,
    UnlinkEntraIdentityInput,
    UserLifecycleResult,
)
from core.users.models import EntraIdentity, User


def set_user_active(*, caller: str, data: SetUserActiveInput) -> UserLifecycleResult:
    """Set activity idempotently and synchronize an existing binding atomically.

    Race guard: lock User before EntraIdentity, then the routing stream. Repeating
    the target state is a no-op; routing publication is also content-idempotent.
    """
    _require_actor(caller, "users.lifecycle.activity.write")
    if not isinstance(data.is_active, bool):
        raise ValueError("is_active must be boolean")
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=data.user_id)
        identity = EntraIdentity.objects.select_for_update().filter(user_id=user.pk).first()
        if user.is_active == data.is_active:
            return UserLifecycleResult(changed=False, user_id=user.pk, identity_id=identity.pk if identity else None)
        user.is_active = data.is_active
        user.save(update_fields=("is_active",))
        if identity is not None:
            publish_user_identity(key=_routing_key(identity), user_is_active=user.is_active)
        return UserLifecycleResult(changed=True, user_id=user.pk, identity_id=identity.pk if identity else None)


def bind_entra_identity(*, caller: str, data: BindEntraIdentityInput) -> UserLifecycleResult:
    """Create or idempotently confirm an Entra binding and publish its eligible key."""
    _require_actor(caller, "users.lifecycle.identity.bind")
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=data.user_id)
        identity = EntraIdentity.objects.select_for_update().filter(user_id=user.pk).first()
        if identity is not None:
            if identity.tenant_id != data.tenant_id or identity.object_id != data.object_id:
                raise ValueError("An existing Entra identity cannot be replaced by this command.")
            return UserLifecycleResult(changed=False, user_id=user.pk, identity_id=identity.pk)
        try:
            with transaction.atomic():
                identity = EntraIdentity.objects.create(user=user, tenant_id=data.tenant_id, object_id=data.object_id)
        except IntegrityError as exc:
            _raise_identity_conflict(exc)
        if user.is_active:
            publish_user_identity(key=_routing_key(identity), user_is_active=True)
        return UserLifecycleResult(changed=True, user_id=user.pk, identity_id=identity.pk)


def replace_entra_identity(*, caller: str, data: ReplaceEntraIdentityInput) -> UserLifecycleResult:
    """Tombstone the previous key, replace the binding, and publish the new key atomically."""
    _require_actor(caller, "users.lifecycle.identity.replace")
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=data.user_id)
        identity = EntraIdentity.objects.select_for_update().filter(user_id=user.pk).first()
        if identity is None:
            try:
                with transaction.atomic():
                    replacement = EntraIdentity.objects.create(
                        user=user, tenant_id=data.tenant_id, object_id=data.object_id
                    )
            except IntegrityError as exc:
                _raise_identity_conflict(exc)
            if user.is_active:
                publish_user_identity(key=_routing_key(replacement), user_is_active=True)
            return UserLifecycleResult(changed=True, user_id=user.pk, identity_id=replacement.pk)
        if (identity.tenant_id, identity.object_id) == (data.tenant_id, data.object_id):
            if user.is_active:
                publish_user_identity(key=_routing_key(identity), user_is_active=True)
            return UserLifecycleResult(changed=False, user_id=user.pk, identity_id=identity.pk)
        old_key = _routing_key(identity)
        publish_user_identity(key=old_key, user_is_active=False)
        identity.delete()
        try:
            with transaction.atomic():
                replacement = EntraIdentity.objects.create(
                    user=user, tenant_id=data.tenant_id, object_id=data.object_id
                )
        except IntegrityError as exc:
            _raise_identity_conflict(exc)
        if user.is_active:
            publish_user_identity(key=_routing_key(replacement), user_is_active=True)
        return UserLifecycleResult(changed=True, user_id=user.pk, identity_id=replacement.pk)


def unlink_entra_identity(*, caller: str, data: UnlinkEntraIdentityInput) -> UserLifecycleResult:
    """Tombstone the persisted identity key before deleting its binding."""
    _require_actor(caller, "users.lifecycle.identity.unlink")
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=data.user_id)
        identity = EntraIdentity.objects.select_for_update().filter(user_id=user.pk).first()
        if identity is None:
            return UserLifecycleResult(changed=False, user_id=user.pk)
        key = _routing_key(identity)
        publish_user_identity(key=key, user_is_active=False)
        identity.delete()
        return UserLifecycleResult(changed=True, user_id=user.pk, identity_id=identity.pk)


def delete_user(*, caller: str, data: DeleteUserInput) -> UserLifecycleResult:
    """Tombstone an eligible identity before deleting the user and protected relation."""
    _require_actor(caller, "users.lifecycle.user.delete")
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=data.user_id)
        identity = EntraIdentity.objects.select_for_update().filter(user_id=user.pk).first()
        identity_id = identity.pk if identity else None
        if identity is not None:
            key = _routing_key(identity)
            publish_user_identity(key=key, user_is_active=False)
            identity.delete()
        user.delete()
        return UserLifecycleResult(changed=True, user_id=data.user_id, identity_id=identity_id)


def _replace_entra_identity_from_operator(data: ReplaceEntraIdentityInput) -> UserLifecycleResult:
    return replace_entra_identity(caller="bind-entra-identity-command", data=data)


def _bind_entra_identity_from_operator(data: BindEntraIdentityInput) -> UserLifecycleResult:
    return bind_entra_identity(caller="bind-entra-identity-command", data=data)


def _unlink_entra_identity_from_operator(data: UnlinkEntraIdentityInput) -> UserLifecycleResult:
    return unlink_entra_identity(caller="bind-entra-identity-command", data=data)


def _delete_user_from_operator(data: DeleteUserInput) -> UserLifecycleResult:
    return delete_user(caller="bind-entra-identity-command", data=data)


def _routing_key(identity: EntraIdentity) -> str:
    """Derive the canonical routing key once while its persisted row is locked."""
    return f"entra:{str(identity.tenant_id).lower()}:{str(identity.object_id).lower()}"


def _raise_identity_conflict(error: IntegrityError) -> None:
    cause = error.__cause__ or error
    constraint_name = getattr(getattr(cause, "diag", None), "constraint_name", None)
    if constraint_name in {"users_entra_unique_subject", "users_entraidentity_user_id_key"}:
        raise ValueError("The Entra identity is already bound.") from error
    raise error


def _require_actor(caller: str, required_capability: str) -> None:
    """Allowlist internal caller labels; this is not an isolation boundary within Python."""
    capabilities_by_caller = {
        "aad-login": frozenset({"users.lifecycle.identity.bind"}),
        "bind-entra-identity-command": frozenset(
            {
                "users.lifecycle.identity.bind",
                "users.lifecycle.identity.replace",
                "users.lifecycle.identity.unlink",
                "users.lifecycle.user.delete",
            }
        ),
        "urs-sync": frozenset({"users.lifecycle.activity.write"}),
    }
    capabilities = capabilities_by_caller.get(caller)
    if capabilities is None or required_capability not in capabilities:
        raise PermissionError("The actor is not authorized for this lifecycle operation.")
