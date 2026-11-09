"""Synthetic regression coverage for the production authentication boundary."""

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
    create_login_challenge,
)
from core.users.features.auth.authentication import EntraJWTAuthentication
from core.users.features.auth.login.ldap_service import ldap_auth
from core.users.features.auth.login.serializer import LoginSerializer
from core.users.features.auth.login.service import AuthenticationError, login
from core.users.features.auth.tokens import rotate_refresh
from core.users.models import EntraIdentity, User


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
    challenge, nonce = create_login_challenge()
    token, payload = signed_token(signing_key, settings, nonce, preferred_username="different@example.com")
    EntraIdentity.objects.create(user=user, tenant_id=payload["tid"], object_id=payload["oid"])
    with mock_jwks(signing_key):
        data, authenticated = aad_login(id_token=token, challenge_id=str(challenge.pk))
        assert authenticated.pk == user.pk
        assert data["username"] == "synthetic-original"
        with pytest.raises(AADAuthError):
            aad_login(id_token=token, challenge_id=str(challenge.pk))
    user.refresh_from_db()
    assert user.email == ""


@pytest.mark.django_db
@pytest.mark.parametrize("failure", ["unmapped", "inactive", "expired", "wrong_nonce", "missing_cookie"])
def test_no_implicit_linking_or_invalid_challenge(signing_key, settings, failure):
    settings.ENTRA_BIND_BY_USERNAME = False
    user = User.objects.create_user(username="synthetic", password=None, is_active=failure != "inactive")
    challenge, nonce = create_login_challenge()
    token, payload = signed_token(
        signing_key, settings, "wrong" if failure == "wrong_nonce" else nonce, preferred_username="synthetic@bosch.com"
    )
    if failure != "unmapped":
        EntraIdentity.objects.create(user=user, tenant_id=payload["tid"], object_id=payload["oid"])
    if failure == "expired":
        challenge.expires_at = timezone.now() - timedelta(seconds=1)
        challenge.save()
    with mock_jwks(signing_key), pytest.raises(AADAuthError):
        aad_login(id_token=token, challenge_id="" if failure == "missing_cookie" else str(challenge.pk))


@pytest.mark.django_db
@pytest.mark.parametrize("case", ["bound", "disabled", "staff", "other_user", "already_bound"])
def test_bind_by_preferred_username(signing_key, settings, case):
    settings.ENTRA_BIND_BY_USERNAME = case != "disabled"
    user = User.objects.create_user(username="uah2hc", password=None, is_staff=case == "staff")
    if case == "already_bound":
        EntraIdentity.objects.create(user=user, tenant_id=settings.AAD_TENANT_ID, object_id=uuid4())
    challenge, nonce = create_login_challenge()
    username = "other" if case == "other_user" else "uah2hc"
    token, payload = signed_token(signing_key, settings, nonce, preferred_username=f"{username}@bosch.com")
    with mock_jwks(signing_key):
        if case == "bound":
            data, authenticated = aad_login(id_token=token, challenge_id=str(challenge.pk))
            assert authenticated.pk == user.pk
            assert EntraIdentity.objects.get(user=user).object_id == uuid_of(payload["oid"])
            key = f"entra:{payload['tid'].lower()}:{payload['oid'].lower()}"
            assert RoutingEntity.objects.get(entity_type="users", key=key).deleted_at is None
            assert RoutingChange.objects.filter(
                entity_type="users", key=key, op=RoutingChange.Operation.UPSERT
            ).exists()
        else:
            with pytest.raises(AADAuthError):
                aad_login(id_token=token, challenge_id=str(challenge.pk))


@pytest.mark.django_db
def test_consumed_challenge_does_not_bind_identity(signing_key, settings):
    settings.ENTRA_BIND_BY_USERNAME = True
    user = User.objects.create_user(username="synthetic-first-login", password=None)
    challenge, nonce = create_login_challenge()
    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["consumed_at"])
    token, payload = signed_token(
        signing_key,
        settings,
        nonce,
        preferred_username="synthetic-first-login@example.com",
    )

    with mock_jwks(signing_key), pytest.raises(AADAuthError):
        aad_login(id_token=token, challenge_id=str(challenge.pk))

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
def test_entra_challenge_is_throttled():
    client = Client()
    responses = [client.post("/api/aad-login/challenge") for _ in range(11)]
    assert responses[-1].status_code == 429
    assert responses[-1].json()["error"]["code"] == "rate_limited"
    assert "Retry-After" in responses[-1]


@pytest.mark.django_db
def test_challenge_login_refresh_logout_browser_flow(signing_key, settings):
    settings.ENTRA_SSO_ONLY = True
    client = Client(enforce_csrf_checks=True)
    response = client.post("/api/aad-login/challenge")
    assert response.status_code == 200
    assert response.cookies[settings.AAD_LOGIN_CHALLENGE_COOKIE]["httponly"]
    data = response.json()["data"]
    token, claims = signed_token(signing_key, settings, data["nonce"])
    user = User.objects.create_user(username="synthetic", password=None)
    EntraIdentity.objects.create(user=user, tenant_id=claims["tid"], object_id=claims["oid"])
    with mock_jwks(signing_key):
        response = client.post(
            "/api/aad-login", {"id_token": token}, content_type="application/json", HTTP_X_CSRFTOKEN=data["csrf_token"]
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
    challenge = client.post("/api/aad-login/challenge").json()["data"]
    token, claims = signed_token(signing_key, settings, challenge["nonce"])
    user = User.objects.create_user(username="synthetic-staff", password=None, is_staff=True)
    EntraIdentity.objects.create(user=user, tenant_id=claims["tid"], object_id=claims["oid"])
    with mock_jwks(signing_key):
        response = client.post(
            "/api/aad-login",
            {"id_token": token},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=challenge["csrf_token"],
        )
    assert response.status_code == 200
    assert client.session["_auth_user_id"] == str(user.pk)
    csrf = response.json()["data"]["csrf_token"]
    assert csrf != challenge["csrf_token"]
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
