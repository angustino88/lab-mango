"""Stub persona injection: guards, idempotency, and routing publication through the lifecycle commands."""

import threading
import uuid

import pytest
from django.db import connection
from django.test import override_settings

from core.routing.models import RoutingChange
from core.users.models import EntraIdentity, RoleAuditEvent, URSGroup, User
from core.users.public import (
    StubIdentitiesDisabled,
    StubUserInput,
    effective_labs_roles,
    ensure_stub_user,
    stub_bind_entra_identity,
    stub_delete_user,
    stub_set_user_active,
)
from tools.stubs import identities
from tools.stubs.common import load_personas

pytestmark = pytest.mark.django_db


def _changes(key):
    return list(
        RoutingChange.objects.filter(entity_type="users", key=key).order_by("version").values_list("op", flat=True)
    )


def test_seed_creates_bound_users_with_roles_and_publishes_eligible_keys(stub_env):
    manifest = load_personas()
    outcomes = {outcome.key: outcome for outcome in identities.seed(manifest)}

    assert set(outcomes) == {key for key, p in manifest.personas.items() if p.backend == "dept_a"}
    alice = User.objects.get(username="stub.alice")
    assert not alice.has_usable_password() and alice.is_urs_managed is False
    assert effective_labs_roles(User.objects.get(username="stub.carol")) >= {"coord", "user"}
    assert effective_labs_roles(User.objects.get(username="stub.nora")) == frozenset()
    assert _changes(manifest.user_key(manifest.get("alice"))) == ["upsert"]
    assert _changes(manifest.user_key(manifest.get("ivy"))) == []  # bound but inactive: not routed
    assert not EntraIdentity.objects.filter(user__username="stub.dave").exists()  # unbound by design
    assert not User.objects.filter(username="stub.bob").exists()  # another backend
    assert RoleAuditEvent.objects.filter(actor_label="system:stub-identities-command").exists()


def test_second_seed_changes_nothing_and_publishes_nothing(stub_env):
    identities.seed()
    versions = RoutingChange.objects.count()

    assert not any(outcome.changed for outcome in identities.seed())
    assert RoutingChange.objects.count() == versions


def test_unlink_replace_delete_publish_tombstones(stub_env):
    manifest = load_personas()
    alice = manifest.get("alice")
    identities.seed(manifest)
    first_key = manifest.user_key(alice)

    identities.unlink(alice)
    assert _changes(first_key) == ["upsert", "delete"]
    identities.seed(manifest, keys=["alice"])
    assert _changes(first_key) == ["upsert", "delete", "upsert"]

    old, new = identities.replace(manifest, alice)
    assert old == first_key and new != old
    assert _changes(old)[-1] == "delete" and _changes(new) == ["upsert"]

    identities.delete(alice)
    assert _changes(new) == ["upsert", "delete"]
    assert not User.objects.filter(username="stub.alice").exists()


def test_object_ids_are_deterministic(stub_home):
    manifest = load_personas()
    alice = manifest.get("alice")
    assert manifest.object_id(alice) == load_personas().object_id(alice)
    assert manifest.object_id(alice, generation=1) != manifest.object_id(alice, generation=0)


def test_stub_groups_are_invisible_to_the_scheduled_urs_sync(stub_env):
    identities.seed()
    stub_groups = URSGroup.objects.filter(urs_group_id__gte=9_000_000_000_001)

    assert stub_groups.count() == 3
    assert not stub_groups.filter(active=True).exists()  # core/users/tasks.py syncs active groups only


@pytest.mark.parametrize(
    "overrides",
    [
        {"ENTRA_STUB_ISSUER_ENABLED": False},
        {"DEBUG": False},
        {"ENTRA_SSO_ONLY": True},
        {"AAD_TENANT_ID": "0ae51e19-07c8-4e4b-bb6d-648ee58410f4"},
    ],
    ids=["flag-off", "not-debug", "sso-only", "real-tenant"],
)
def test_every_stub_command_refuses_outside_local_stub_mode(stub_env, overrides):
    with override_settings(**overrides), pytest.raises(StubIdentitiesDisabled):
        ensure_stub_user(StubUserInput(username="stub.x", name="X", email="x@stub.labmango.test"))


def test_real_users_are_never_touched(stub_env):
    real = User.objects.create(username="real.person", email="real@example.com")
    urs_managed = User.objects.create(username="stub.managed", is_urs_managed=True)

    for user in (real, urs_managed):
        for command in (
            lambda: stub_bind_entra_identity(user_id=user.pk, object_id=uuid.uuid4()),
            lambda: stub_set_user_active(user_id=user.pk, is_active=False),
            lambda: stub_delete_user(user_id=user.pk),
        ):
            with pytest.raises(StubIdentitiesDisabled):
                command()
    with pytest.raises(StubIdentitiesDisabled):
        ensure_stub_user(StubUserInput(username="real.person", name="R", email="r@example.com"))
    assert User.objects.filter(pk__in=[real.pk, urs_managed.pk], is_active=True).count() == 2


def test_stub_user_bound_in_another_tenant_is_refused(stub_env):
    user_id = ensure_stub_user(StubUserInput(username="stub.other", name="O", email="o@stub.labmango.test")).user_id
    EntraIdentity.objects.create(user_id=user_id, tenant_id=uuid.uuid4(), object_id=uuid.uuid4())

    with pytest.raises(StubIdentitiesDisabled):
        stub_delete_user(user_id=user_id)


@pytest.mark.django_db(transaction=True)
def test_concurrent_seeds_create_one_user_binding_and_routing_upsert(stub_env):
    manifest = load_personas()
    errors = []

    def run():
        try:
            identities.seed(manifest, keys=["alice"])
        except Exception as exc:  # collected and asserted below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert User.objects.filter(username="stub.alice").count() == 1
    assert EntraIdentity.objects.filter(user__username="stub.alice").count() == 1
    assert _changes(manifest.user_key(manifest.get("alice"))) == ["upsert"]
