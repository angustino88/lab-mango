"""Synthetic regression coverage for the production authentication boundary."""

import hashlib
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import MagicMock, patch
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.cache import cache
from django.db import IntegrityError, close_old_connections, transaction
from django.test import Client
from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from core.labs.models import RoutingChange, RoutingEntity
from core.users.backends import EntraSessionBackend
from core.users.features.auth.aad_login.service import (
    AADAuthError,
    _decode_id_token,
    aad_login,
    nonce_for_secret,
)
from core.users.features.auth.authentication import EntraJWTAuthentication
from core.users.features.auth.login.ldap_service import ldap_auth
from core.users.features.auth.login.serializer import LoginSerializer
from core.users.features.auth.login.service import AuthenticationError, login
from core.users.features.auth.tokens import rotate_refresh
from core.users.models import EntraIdentity, EntraLoginNonce, User


@pytest.fixture(autouse=True)
def reset_throttles():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def signed_token(key, settings, nonce="nonce", **overrides):
    now = int(time.time())
    payload = {
        "iss": settings.AAD_ISSUER,
        "aud": settings.AAD_AUDIENCE,
        "tid": settings.AAD_TENANT_ID,
        "oid": str(uuid4()),
        "sub": "synthetic-subject",
        "iat": now - 10,
        "nbf": now - 10,
        "exp": now + 300,
        "nonce": nonce,
    }
    payload.update(overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, key, algorithm="RS256"), payload


def login_nonce():
    """The browser's secret and the nonce it sends to Microsoft."""
    secret = secrets.token_urlsafe(32)
    return secret, nonce_for_secret(secret)


def mock_jwks(key):
    client = MagicMock()
    client.get_signing_key_from_jwt.return_value.key = key.public_key()
    return patch("core.users.features.auth.aad_login.service._jwks_client", return_value=client)


@pytest.mark.parametrize(
    "claim,value",
    [
        ("iss", "https://invalid.example/v2.0"),
        ("tid", str(uuid4())),
        ("aud", "wrong-audience"),
        ("oid", "invalid"),
        ("exp", 1),
        ("exp", None),
        ("sub", None),
        ("nonce", None),
        ("nbf", None),
        ("iat", None),
        ("nbf", 4102444800),
        ("nonce", 42),
    ],
)
def test_rejects_invalid_claims(signing_key, settings, claim, value):
    token, _ = signed_token(signing_key, settings, **{claim: value})
    with mock_jwks(signing_key), pytest.raises(AADAuthError):
        _decode_id_token(token)


@pytest.mark.django_db
def test_stable_identity_and_one_use_nonce(signing_key, settings):
    user = User.objects.create_user(username="synthetic-original", password=None)
    secret, nonce = login_nonce()
    token, payload = signed_token(signing_key, settings, nonce, preferred_username="different@example.com")
    EntraIdentity.objects.create(user=user, tenant_id=payload["tid"], object_id=payload["oid"])
    with mock_jwks(signing_key):
        data, authenticated = aad_login(id_token=token, nonce_secret=secret)
        assert authenticated.pk == user.pk
        assert data["username"] == "synthetic-original"
        with pytest.raises(AADAuthError):
            aad_login(id_token=token, nonce_secret=secret)
    user.refresh_from_db()
    assert user.email == ""


@pytest.mark.django_db
@pytest.mark.parametrize("failure", ["unmapped", "inactive", "stale_token", "wrong_nonce", "missing_secret"])
def test_no_implicit_linking_or_invalid_nonce(signing_key, settings, failure):
    settings.ENTRA_BIND_BY_USERNAME = False
    user = User.objects.create_user(username="synthetic", password=None, is_active=failure != "inactive")
    secret, nonce = login_nonce()
    stale = {"iat": int(time.time()) - 3600} if failure == "stale_token" else {}
    token, payload = signed_token(
        signing_key,
        settings,
        "wrong" if failure == "wrong_nonce" else nonce,
        preferred_username="synthetic@bosch.com",
        **stale,
    )
    if failure != "unmapped":
        EntraIdentity.objects.create(user=user, tenant_id=payload["tid"], object_id=payload["oid"])
    with mock_jwks(signing_key), pytest.raises(AADAuthError):
        aad_login(id_token=token, nonce_secret="" if failure == "missing_secret" else secret)


@pytest.mark.django_db
@pytest.mark.parametrize("case", ["bound", "disabled", "staff", "other_user", "already_bound"])
def test_bind_by_preferred_username(signing_key, settings, case):
    settings.ENTRA_BIND_BY_USERNAME = case != "disabled"
    user = User.objects.create_user(username="uah2hc", password=None, is_staff=case == "staff")
    if case == "already_bound":
        EntraIdentity.objects.create(user=user, tenant_id=settings.AAD_TENANT_ID, object_id=uuid4())
    secret, nonce = login_nonce()
    username = "other" if case == "other_user" else "uah2hc"
    token, payload = signed_token(signing_key, settings, nonce, preferred_username=f"{username}@bosch.com")
    with mock_jwks(signing_key):
        if case == "bound":
            data, authenticated = aad_login(id_token=token, nonce_secret=secret)
            assert authenticated.pk == user.pk
            assert EntraIdentity.objects.get(user=user).object_id == uuid_of(payload["oid"])
            key = f"entra:{payload['tid'].lower()}:{payload['oid'].lower()}"
            assert RoutingEntity.objects.get(entity_type="users", key=key).deleted_at is None
            assert RoutingChange.objects.filter(
                entity_type="users", key=key, op=RoutingChange.Operation.UPSERT
            ).exists()
        else:
            with pytest.raises(AADAuthError):
                aad_login(id_token=token, nonce_secret=secret)


@pytest.mark.django_db
def test_used_nonce_does_not_bind_identity(signing_key, settings):
    settings.ENTRA_BIND_BY_USERNAME = True
    user = User.objects.create_user(username="synthetic-first-login", password=None)
    secret, nonce = login_nonce()
    EntraLoginNonce.objects.create(
        nonce_digest=hashlib.sha256(nonce.encode()).hexdigest(), expires_at=timezone.now() + timedelta(minutes=10)
    )
    token, payload = signed_token(
        signing_key,
        settings,
        nonce,
        preferred_username="synthetic-first-login@example.com",
    )

    with mock_jwks(signing_key), pytest.raises(AADAuthError):
        aad_login(id_token=token, nonce_secret=secret)

    assert not EntraIdentity.objects.filter(user=user).exists()
    assert not RoutingEntity.objects.filter(
        entity_type="users", key=f"entra:{payload['tid'].lower()}:{payload['oid'].lower()}"
    ).exists()


def uuid_of(value):
    from uuid import UUID

    return UUID(value)


@pytest.mark.django_db
def test_database_constraints():
    user = User.objects.create_user(username="synthetic", password=None)
    assert user.account_type == "CUSTOMER"
    assert user.status == "OFFLINE"
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(account_type="INVALID")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(status="INVALID")
    subject = dict(tenant_id=uuid4(), object_id=uuid4())
    EntraIdentity.objects.create(user=user, **subject)
    other = User.objects.create_user(username="synthetic-other", password=None)
    with pytest.raises(IntegrityError), transaction.atomic():
        EntraIdentity.objects.create(user=other, **subject)


def test_password_whitespace_preserved():
    serializer = LoginSerializer(data={"username": "synthetic", "password": "  pass  "})
    assert serializer.is_valid()
    assert serializer.validated_data["password"] == "  pass  "


def test_production_rejects_password_and_ldap_without_network(settings):
    settings.ENTRA_SSO_ONLY = True
    assert EntraSessionBackend().authenticate(None, username="admin", password="synthetic") is None
    with patch("core.users.features.auth.login.ldap_service.Connection") as connection:
        assert ldap_auth("admin", "synthetic") is None
        connection.assert_not_called()
    with pytest.raises(AuthenticationError):
        login(username="admin", password="synthetic")


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/api/aad-login", "/api/refresh-token", "/api/logout"])
def test_cookie_endpoints_require_csrf(path):
    response = Client(enforce_csrf_checks=True).post(path, data={}, content_type="application/json")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"
    assert "request_id" in response.json()["error"]


@pytest.mark.django_db
def test_entra_login_is_throttled():
    client = Client()
    responses = [client.post("/api/aad-login", {}, content_type="application/json") for _ in range(11)]
    assert responses[-1].status_code == 429
    assert responses[-1].json()["error"]["code"] == "rate_limited"
    assert "Retry-After" in responses[-1]


@pytest.mark.django_db
def test_csrf_login_refresh_logout_browser_flow(signing_key, settings):
    settings.ENTRA_SSO_ONLY = True
    client = Client(enforce_csrf_checks=True)
    response = client.get("/api/csrf-token")
    assert response.status_code == 200
    data = response.json()["data"]
    secret, nonce = login_nonce()
    token, claims = signed_token(signing_key, settings, nonce)
    user = User.objects.create_user(username="synthetic", password=None)
    EntraIdentity.objects.create(user=user, tenant_id=claims["tid"], object_id=claims["oid"])
    with mock_jwks(signing_key):
        response = client.post(
            "/api/aad-login",
            {"id_token": token, "nonce_secret": secret},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=data["csrf_token"],
        )
    assert response.status_code == 200
    assert "refresh" not in response.json()["data"]
    assert response.cookies["refresh_token"]["httponly"]
    access = response.json()["data"]["access"]
    authentication = EntraJWTAuthentication()
    assert authentication.get_user(authentication.get_validated_token(access)).pk == user.pk
    response = client.post("/api/refresh-token", HTTP_X_CSRFTOKEN=data["csrf_token"])
    assert response.status_code == 200
    response = client.post("/api/logout", HTTP_X_CSRFTOKEN=data["csrf_token"])
    assert response.status_code == 200, response.content


@pytest.mark.django_db
def test_old_refresh_tokens_rejected_at_cutover(settings):
    user = User.objects.create_user(username="synthetic-legacy", password=None)
    raw = str(RefreshToken.for_user(user))
    settings.ENTRA_SSO_ONLY = True
    with pytest.raises(TokenError):
        rotate_refresh(raw_token=raw)


@pytest.mark.django_db
def test_websocket_rejects_legacy_tokens(settings):
    from core.websocket.middleware import _validate_token

    user = User.objects.create_user(username="synthetic-websocket", password=None)
    raw = str(RefreshToken.for_user(user).access_token)
    settings.ENTRA_SSO_ONLY = True
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_AUTHENTICATION_CLASSES": ("core.users.features.auth.authentication.EntraJWTAuthentication",),
    }
    assert _validate_token(raw) is None


@pytest.mark.django_db
def test_staff_sso_session_csrf_rotation(signing_key, settings):
    settings.ENTRA_SSO_ONLY = True
    settings.AUTHENTICATION_BACKENDS = ["core.users.backends.EntraSessionBackend"]
    client = Client(enforce_csrf_checks=True)
    csrf_data = client.get("/api/csrf-token").json()["data"]
    secret, nonce = login_nonce()
    token, claims = signed_token(signing_key, settings, nonce)
    user = User.objects.create_user(username="synthetic-staff", password=None, is_staff=True)
    EntraIdentity.objects.create(user=user, tenant_id=claims["tid"], object_id=claims["oid"])
    with mock_jwks(signing_key):
        response = client.post(
            "/api/aad-login",
            {"id_token": token, "nonce_secret": secret},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_data["csrf_token"],
        )
    assert response.status_code == 200
    assert client.session["_auth_user_id"] == str(user.pk)
    csrf = response.json()["data"]["csrf_token"]
    assert csrf != csrf_data["csrf_token"]
    assert client.post("/api/logout", HTTP_X_CSRFTOKEN=csrf).status_code == 200
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_operator_binding_is_explicit_and_idempotent(settings):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    user = User.objects.create_user(username="synthetic-bootstrap", password="synthetic-password")
    settings.ENTRA_SSO_ONLY = True
    object_id = uuid4()
    call_command("bind_entra_identity", user.username, str(object_id), skip_checks=True)
    call_command("bind_entra_identity", user.username, str(object_id), skip_checks=True)
    user.refresh_from_db()
    assert not user.has_usable_password()
    assert EntraIdentity.objects.filter(user=user, object_id=object_id).count() == 1
    with pytest.raises(CommandError):
        call_command("bind_entra_identity", user.username, str(uuid4()), skip_checks=True)


def test_production_routes_have_no_password_or_otp(settings):
    import importlib

    from core.users.features.auth import urls

    settings.ENTRA_SSO_ONLY = True
    try:
        routes = importlib.reload(urls).urlpatterns
        modules = [entry.urlconf_name.__name__ for entry in routes]
        assert not any(".login.urls" in name or ".send_otp." in name for name in modules)
    finally:
        settings.ENTRA_SSO_ONLY = False
        importlib.reload(urls)


def test_configuration_fails_closed(settings):
    from core.users.checks import check_entra_configuration

    settings.ENTRA_SSO_ONLY = True
    settings.AUTHENTICATION_BACKENDS = ["core.users.backends.EntraSessionBackend"]
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_AUTHENTICATION_CLASSES": ("core.users.features.auth.authentication.EntraJWTAuthentication",),
    }
    assert not check_entra_configuration(None)
    settings.AAD_ISSUER = "https://wrong.example/"
    assert "users.E002" in [error.id for error in check_entra_configuration(None)]


@pytest.mark.django_db
def test_refresh_replay_and_inactive_user():
    user = User.objects.create_user(username="synthetic", password=None)
    raw = str(RefreshToken.for_user(user))
    assert "access" in rotate_refresh(raw_token=raw)
    with pytest.raises(TokenError):
        rotate_refresh(raw_token=raw)
    raw = str(RefreshToken.for_user(user))
    user.is_active = False
    user.save()
    with pytest.raises(TokenError):
        rotate_refresh(raw_token=raw)


@pytest.mark.django_db(transaction=True)
def test_concurrent_refresh_has_only_one_winner():
    user = User.objects.create_user(username="synthetic-concurrent", password=None)
    raw = str(RefreshToken.for_user(user))
    barrier = Barrier(2)

    def attempt():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            rotate_refresh(raw_token=raw)
            return True
        except TokenError:
            return False
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == [False, True]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "case, preferred, extra",
    [
        ("foreign_domain", "uah3hc@partner.example", {}),
        ("guest_upn", "uah3hc_partner.example#EXT#@bosch.com", {}),
        ("guest_claim", "uah3hc@bosch.com", {"acct": 1}),
        ("no_domain", "uah3hc", {}),
    ],
)
def test_first_login_binding_refuses_guests_and_foreign_domains(signing_key, settings, case, preferred, extra):
    settings.ENTRA_BIND_BY_USERNAME = True
    settings.ENTRA_BIND_ALLOWED_DOMAINS = ["bosch.com"]
    user = User.objects.create_user(username="uah3hc", password=None)
    secret, nonce = login_nonce()
    token, _ = signed_token(signing_key, settings, nonce, preferred_username=preferred, **extra)

    with mock_jwks(signing_key), pytest.raises(AADAuthError):
        aad_login(id_token=token, nonce_secret=secret)
    assert not EntraIdentity.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_first_login_binding_is_audited_and_never_repeated_after_unlink(signing_key, settings):
    from core.users.models import RoleAuditEvent
    from core.users.public import UnlinkEntraIdentityInput, unlink_entra_identity

    settings.ENTRA_BIND_BY_USERNAME = True
    settings.ENTRA_BIND_ALLOWED_DOMAINS = ["bosch.com"]
    user = User.objects.create_user(username="uah4hc", password=None)

    secret, nonce = login_nonce()
    token, payload = signed_token(signing_key, settings, nonce, preferred_username="uah4hc@bosch.com")
    with mock_jwks(signing_key):
        aad_login(id_token=token, nonce_secret=secret)
    bound = RoleAuditEvent.objects.get(event_type="entra_identity_bound", target_user_id=user.pk)
    assert bound.actor_label == "system:aad-login"
    assert bound.changes["object_id"] == payload["oid"].lower()

    unlink_entra_identity(data=UnlinkEntraIdentityInput(user_id=user.pk))
    assert RoleAuditEvent.objects.filter(event_type="entra_identity_unlinked", target_user_id=user.pk).exists()

    # A different Microsoft account with the same username must not take over the unlinked account.
    secret, nonce = login_nonce()
    token, _ = signed_token(signing_key, settings, nonce, preferred_username="uah4hc@bosch.com")
    with mock_jwks(signing_key), pytest.raises(AADAuthError):
        aad_login(id_token=token, nonce_secret=secret)
    assert not EntraIdentity.objects.filter(user=user).exists()


def test_production_requires_allowed_domains_for_username_binding(settings):
    from core.users.checks import check_entra_configuration

    settings.ENTRA_SSO_ONLY = True
    settings.ENTRA_BIND_BY_USERNAME = True
    settings.ENTRA_BIND_ALLOWED_DOMAINS = []

    assert "users.E009" in {error.id for error in check_entra_configuration(None)}


@pytest.mark.django_db
def test_nonce_must_match_the_secret_and_is_single_use(signing_key, settings):
    user = User.objects.create_user(username="synthetic-nonce", password=None)
    secret, nonce = login_nonce()
    other_secret, _ = login_nonce()
    token, payload = signed_token(signing_key, settings, nonce)
    EntraIdentity.objects.create(user=user, tenant_id=payload["tid"], object_id=payload["oid"])

    with mock_jwks(signing_key):
        with pytest.raises(AADAuthError):
            aad_login(id_token=token, nonce_secret=other_secret)  # someone holding only the token
        aad_login(id_token=token, nonce_secret=secret)
        with pytest.raises(AADAuthError):
            aad_login(id_token=token, nonce_secret=secret)  # replay of a used token
    assert EntraLoginNonce.objects.count() == 1


def test_nonce_for_secret_is_base64url_sha256_without_padding():
    assert nonce_for_secret("a" * 43) == "ZtNPunH49FD35FWYhT5Tv8I7vRKQJ8uxMaL0_9eHjNA"


@pytest.mark.django_db
def test_csrf_token_endpoint_sets_cookie_without_database_writes(django_assert_num_queries):
    client = Client(enforce_csrf_checks=True)
    with django_assert_num_queries(0):
        response = client.get("/api/csrf-token")
    assert response.status_code == 200
    assert response.json()["data"]["csrf_token"]
    assert "csrftoken" in response.cookies
    assert response["Cache-Control"] == "no-store"
