"""User lifecycle routing synchronization tests."""

from uuid import uuid4

import pytest

from core.labs.models import RoutingChange, RoutingEntity, SyncState
from core.users.features.lifecycle.application import set_user_active as set_user_active_command
from core.users.features.lifecycle.public import (
    BindEntraIdentityInput,
    DeleteUserInput,
    ReplaceEntraIdentityInput,
    SetUserActiveInput,
    UnlinkEntraIdentityInput,
)
from core.users.models import EntraIdentity
from core.users.public import (
    bind_entra_identity as bind_entra_identity_from_public,
)
from core.users.public import (
    delete_user as delete_user_from_public,
)
from core.users.public import (
    replace_entra_identity as replace_entra_identity_from_public,
)
from core.users.public import (
    set_user_active as set_user_active_from_public,
)
from core.users.public import (
    unlink_entra_identity as unlink_entra_identity_from_public,
)
from core.users.tests.factories import UserFactory


@pytest.mark.django_db
def test_lifecycle_rejects_untrusted_callers():
    user = UserFactory()

    with pytest.raises(PermissionError):
        set_user_active_command(
            caller="untrusted-caller",
            data=SetUserActiveInput(user_id=user.pk, is_active=False),
        )


@pytest.mark.django_db(transaction=True)
def test_bind_is_idempotent_and_only_active_users_are_published():
    active, inactive = UserFactory(), UserFactory(is_active=False)
    active_pair = (uuid4(), uuid4())
    inactive_pair = (uuid4(), uuid4())

    result = bind_entra_identity_from_public(
        data=BindEntraIdentityInput(user_id=active.pk, tenant_id=active_pair[0], object_id=active_pair[1])
    )
    repeated = bind_entra_identity_from_public(
        data=BindEntraIdentityInput(user_id=active.pk, tenant_id=active_pair[0], object_id=active_pair[1]),
    )
    bind_entra_identity_from_public(
        data=BindEntraIdentityInput(user_id=inactive.pk, tenant_id=inactive_pair[0], object_id=inactive_pair[1]),
    )

    active_key = f"entra:{active_pair[0]}:{active_pair[1]}"
    inactive_key = f"entra:{inactive_pair[0]}:{inactive_pair[1]}"
    assert result.changed and not repeated.changed
    assert RoutingEntity.objects.get(entity_type="users", key=active_key).deleted_at is None
    assert not RoutingEntity.objects.filter(entity_type="users", key=inactive_key).exists()
    assert SyncState.objects.get(pk="users").version == 1


@pytest.mark.django_db(transaction=True)
def test_activity_change_unlink_and_delete_keep_old_key_tombstones():
    user = UserFactory()
    tenant_id, object_id = uuid4(), uuid4()
    bind_entra_identity_from_public(
        data=BindEntraIdentityInput(user_id=user.pk, tenant_id=tenant_id, object_id=object_id)
    )
    key = f"entra:{tenant_id}:{object_id}"

    set_user_active_from_public(data=SetUserActiveInput(user_id=user.pk, is_active=False))
    assert RoutingEntity.objects.get(entity_type="users", key=key).deleted_at is not None
    set_user_active_from_public(data=SetUserActiveInput(user_id=user.pk, is_active=True))
    assert RoutingEntity.objects.get(entity_type="users", key=key).deleted_at is None
    unlink_entra_identity_from_public(data=UnlinkEntraIdentityInput(user_id=user.pk))
    assert not EntraIdentity.objects.filter(user_id=user.pk).exists()
    assert RoutingEntity.objects.get(entity_type="users", key=key).deleted_at is not None

    new_pair = (uuid4(), uuid4())
    bind_entra_identity_from_public(
        data=BindEntraIdentityInput(user_id=user.pk, tenant_id=new_pair[0], object_id=new_pair[1])
    )
    new_key = f"entra:{new_pair[0]}:{new_pair[1]}"
    delete_user_from_public(data=DeleteUserInput(user_id=user.pk))
    assert not EntraIdentity.objects.filter(user_id=user.pk).exists()
    assert RoutingEntity.objects.get(entity_type="users", key=new_key).deleted_at is not None
    assert RoutingChange.objects.filter(entity_type="users", key=key, op=RoutingChange.Operation.DELETE).exists()


@pytest.mark.django_db(transaction=True)
def test_identity_replacement_tombstones_old_key_before_upserting_new():
    user = UserFactory()
    original = (uuid4(), uuid4())
    replacement = (uuid4(), uuid4())
    bind_entra_identity_from_public(
        data=BindEntraIdentityInput(user_id=user.pk, tenant_id=original[0], object_id=original[1])
    )
    result = replace_entra_identity_from_public(
        data=ReplaceEntraIdentityInput(user_id=user.pk, tenant_id=replacement[0], object_id=replacement[1]),
    )

    old_key = f"entra:{original[0]}:{original[1]}"
    new_key = f"entra:{replacement[0]}:{replacement[1]}"
    assert result.changed
    assert RoutingEntity.objects.get(entity_type="users", key=old_key).deleted_at is not None
    assert RoutingEntity.objects.get(entity_type="users", key=new_key).deleted_at is None
    assert list(
        RoutingChange.objects.filter(entity_type="users").order_by("version").values_list("op", flat=True)
    ) == [RoutingChange.Operation.UPSERT, RoutingChange.Operation.DELETE, RoutingChange.Operation.UPSERT]


@pytest.mark.django_db(transaction=True)
def test_lifecycle_routing_failure_rolls_back_domain_change(monkeypatch):
    user = UserFactory()
    tenant_id, object_id = uuid4(), uuid4()
    bind_entra_identity_from_public(
        data=BindEntraIdentityInput(user_id=user.pk, tenant_id=tenant_id, object_id=object_id)
    )

    def fail_publish(**kwargs):
        raise RuntimeError("synthetic publisher failure")

    monkeypatch.setattr("core.users.features.lifecycle.application.publish_user_identity", fail_publish)
    with pytest.raises(RuntimeError, match="synthetic publisher failure"):
        set_user_active_from_public(data=SetUserActiveInput(user_id=user.pk, is_active=False))

    user.refresh_from_db()
    assert user.is_active is True
    assert SyncState.objects.get(pk="users").version == 1


@pytest.mark.django_db(transaction=True)
def test_lifecycle_command_is_atomic_on_publisher_failure(monkeypatch):
    user = UserFactory()
    tenant_id, object_id = uuid4(), uuid4()

    def fail_publish(**kwargs):
        raise RuntimeError("synthetic publisher failure")

    monkeypatch.setattr("core.users.features.lifecycle.application.publish_user_identity", fail_publish)
    with pytest.raises(RuntimeError, match="synthetic publisher failure"):
        bind_entra_identity_from_public(
            data=BindEntraIdentityInput(user_id=user.pk, tenant_id=tenant_id, object_id=object_id)
        )
    assert not EntraIdentity.objects.filter(user_id=user.pk).exists()
