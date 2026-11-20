"""Stub Entra tokens pass the unchanged production validators, and each fault flag is refused."""

import pytest
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from core.routing.models import RoutingChange
from core.users.features.auth.access_token import verify_access_token
from core.users.models import EntraIdentity
from tools.stubs import identities
from tools.stubs.common import load_personas
from tools.stubs.entra import Faults
from tools.stubs.testing import stub_entra_environment

pytestmark = pytest.mark.django_db


def _login(issuer, key, faults=Faults()):
    token, nonce_secret = issuer.id_token(issuer.manifest.get(key), faults=faults)
    return APIClient().post("/api/aad-login", {"id_token": token, "nonce_secret": nonce_secret}, format="json")


def _sync_info(token):
    return APIClient().get("/internal/info", HTTP_AUTHORIZATION=f"Bearer {token}")


def test_bound_persona_logs_in_and_gets_an_entra_session(stub_env):
    identities.seed()
    response = _login(stub_env, "alice")

    assert response.status_code == 200
    assert response.json()["data"]["username"] == "stub.alice"
    token = response.json()["data"]["access"]
    assert APIClient().get("/api/users/me", HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 200


@pytest.mark.parametrize(
    "faults",
    [
        Faults(expired=True),
        Faults(not_yet_valid=True),
        Faults(stale_iat=True),
        Faults(audience="someone-else"),
        Faults(tenant="11111111-2222-4333-8444-555555555555"),
        Faults(unknown_kid=True),
        Faults(hs256=True),
    ],
    ids=["expired", "not-yet-valid", "stale-iat", "wrong-aud", "wrong-tenant", "unknown-kid", "hs256"],
)
def test_login_refuses_every_token_fault(stub_env, faults):
    identities.seed()
    assert _login(stub_env, "alice", faults).status_code == 401


def test_inactive_persona_cannot_log_in(stub_env):
    identities.seed()
    assert _login(stub_env, "ivy").status_code == 401


def test_unbound_persona_binds_on_first_login_and_is_published(stub_env):
    identities.seed()
    manifest = load_personas()
    dave = manifest.get("dave")

    assert _login(stub_env, "dave").status_code == 200
    assert EntraIdentity.objects.filter(user__username="stub.dave", object_id=manifest.object_id(dave)).exists()
    assert RoutingChange.objects.filter(entity_type="users", key=manifest.user_key(dave), op="upsert").exists()


def test_guest_token_does_not_bind(stub_env):
    identities.seed()
    assert _login(stub_env, "dave", Faults(guest=True)).status_code == 401
    assert not EntraIdentity.objects.filter(user__username="stub.dave").exists()


def test_delegated_access_token_is_accepted_and_app_token_is_not(stub_env):
    alice = stub_env.manifest.get("alice")
    claims = verify_access_token(stub_env.access_token(alice))
    assert claims["oid"] == str(stub_env.manifest.object_id(alice))

    with pytest.raises(PermissionDenied):
        verify_access_token(stub_env.access_token(alice, scope="Other.Scope"))
    with pytest.raises(PermissionDenied):
        verify_access_token(stub_env.app_token(audience=f"api://{stub_env.audience}"))


def test_routing_sync_accepts_the_stub_app_token(stub_env):
    assert _sync_info(stub_env.app_token()).status_code == 200


@pytest.mark.parametrize(
    ("faults", "status"),
    [
        (Faults(no_role=True), 403),
        (Faults(with_scp=True), 403),
        (Faults(expired=True), 401),
        (Faults(audience="api://labmango-other"), 401),
        (Faults(tenant="11111111-2222-4333-8444-555555555555"), 401),
        (Faults(unknown_kid=True), 401),
    ],
    ids=["no-role", "with-scp", "expired", "wrong-aud", "wrong-tenant", "unknown-kid"],
)
def test_routing_sync_refuses_app_token_faults(stub_env, faults, status):
    assert _sync_info(stub_env.app_token(faults=faults)).status_code == status


def test_unreachable_jwks_is_unavailable_for_sync_and_refused_for_login(stub_issuer, stub_home):
    with stub_entra_environment(stub_issuer):
        identities.seed()
    with stub_entra_environment(stub_issuer, unreachable=True):
        assert _sync_info(stub_issuer.app_token()).status_code == 503
        assert _login(stub_issuer, "alice").status_code == 401
