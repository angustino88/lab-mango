"""Tests for core.users.public interface."""

from uuid import uuid4

import pytest

from core.users.public import (
    BindEntraIdentityInput,
    DeleteUserInput,
    ReplaceEntraIdentityInput,
    SetUserActiveInput,
    UnlinkEntraIdentityInput,
    VerifiedTeamsRecipient,
    resolve_notification_recipient,
    resolve_teams_recipient,
)


@pytest.mark.django_db
def test_resolve_teams_recipient(django_user_model):
    tenant_id = uuid4()
    object_id = uuid4()
    user = django_user_model.objects.create_user(
        username="test_teams_user",
        password="password123",
        is_active=True,
    )

    # When no EntraIdentity exists
    assert resolve_teams_recipient(user_id=user.pk, expected_tenant_id=tenant_id) is None
    assert resolve_teams_recipient(user_id=user.pk, expected_tenant_id=None) is None

    # When EntraIdentity exists
    from core.users.models import EntraIdentity

    EntraIdentity.objects.create(
        user=user,
        tenant_id=tenant_id,
        object_id=object_id,
    )

    resolved = resolve_teams_recipient(user_id=user.pk, expected_tenant_id=tenant_id)
    assert resolved == VerifiedTeamsRecipient(tenant_id=tenant_id, object_id=object_id)

    # Wrong tenant
    assert resolve_teams_recipient(user_id=user.pk, expected_tenant_id=uuid4()) is None


@pytest.mark.django_db
def test_resolve_notification_recipient(django_user_model):
    tenant_id = uuid4()
    object_id = uuid4()
    user = django_user_model.objects.create_user(
        username="test_notice_user",
        email="notice@example.com",
        password="password123",
        is_active=True,
    )

    # Without teams identity
    profile = resolve_notification_recipient(user_id=user.pk)
    assert profile is not None
    assert profile.user_id == user.pk
    assert profile.username == "test_notice_user"
    assert profile.email == "notice@example.com"
    assert profile.is_active is True
    assert profile.teams_recipient is None

    # Non-existent user
    assert resolve_notification_recipient(user_id=999999) is None

    # With teams identity
    from core.users.models import EntraIdentity

    EntraIdentity.objects.create(
        user=user,
        tenant_id=tenant_id,
        object_id=object_id,
    )

    profile_with_teams = resolve_notification_recipient(
        user_id=user.pk,
        expected_teams_tenant_id=tenant_id,
    )
    assert profile_with_teams is not None
    assert profile_with_teams.teams_recipient == VerifiedTeamsRecipient(
        tenant_id=tenant_id,
        object_id=object_id,
    )


def test_lifecycle_commands_are_exported_from_users_public():
    from core.users.public import (
        bind_entra_identity,
        bind_entra_identity_from_operator,
        delete_user,
        replace_entra_identity,
        set_user_active,
        unlink_entra_identity,
    )

    assert all(
        callable(command)
        for command in (bind_entra_identity, bind_entra_identity_from_operator, delete_user, replace_entra_identity)
    )
    assert all(callable(command) for command in (set_user_active, unlink_entra_identity))
    assert SetUserActiveInput(user_id=17, is_active=False).is_active is False
    assert DeleteUserInput(user_id=17).user_id == 17
    assert UnlinkEntraIdentityInput(user_id=17).user_id == 17
    tenant_id, object_id = uuid4(), uuid4()
    assert BindEntraIdentityInput(user_id=17, tenant_id=tenant_id, object_id=object_id).user_id == 17
    assert ReplaceEntraIdentityInput(user_id=17, tenant_id=tenant_id, object_id=object_id).user_id == 17


def test_lifecycle_command_boundary_has_explicit_exports():
    from core.users.features.lifecycle.public import __all__

    assert set(__all__) == {
        "BindEntraIdentityInput",
        "DeleteUserInput",
        "ReplaceEntraIdentityInput",
        "SetUserActiveInput",
        "UnlinkEntraIdentityInput",
        "UserLifecycleResult",
        "bind_entra_identity",
        "delete_user",
        "has_ever_been_bound",
        "replace_entra_identity",
        "set_user_active",
        "unlink_entra_identity",
    }
