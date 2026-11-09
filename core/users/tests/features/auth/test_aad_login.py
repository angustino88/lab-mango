import hashlib
import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.utils import timezone

from core.users.models import EntraIdentity


def make_test_id_token(
    private_key, *, username="testuser", name="Test User", expired=False, nonce="synthetic-nonce", object_id=None
):
    """Generate a signed RS256 JWT for testing AAD login."""
    now = int(time.time())
    payload = {
        "samaccountname": username,
        "name": name,
        "preferred_username": f"{username}@bosch.com",
        "aud": "eb57f92a-fe50-46b7-b0d8-775cb6b9bdc6",
        "iss": settings.AAD_ISSUER,
        "tid": settings.AAD_TENANT_ID,
        "oid": str(object_id or uuid4()),
        "sub": "synthetic-subject",
        "nonce": nonce,
        "nbf": now - 60,
        "iat": now - 60,
        "exp": now - 10 if expired else now + 3600,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


@pytest.fixture(scope="module")
def rsa_key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_aad_login_success(api_client, user, rsa_key_pair):
    user.username = "testuser"
    await user.asave()

    challenge = await api_client.post("/api/aad-login/challenge")
    object_id = uuid4()
    await EntraIdentity.objects.acreate(user=user, tenant_id=settings.AAD_TENANT_ID, object_id=object_id)
    id_token = make_test_id_token(
        rsa_key_pair,
        username="testuser",
        name="Test User",
        nonce=challenge.json()["data"]["nonce"],
        object_id=object_id,
    )

    mock_signing_key = MagicMock()
    mock_signing_key.key = rsa_key_pair.public_key()

    with patch("core.users.features.auth.aad_login.service._jwks_client") as MockClient:
        mock_client_instance = MagicMock()
        mock_client_instance.get_signing_key_from_jwt.return_value = mock_signing_key
        MockClient.return_value = mock_client_instance

        resp = await api_client.post(
            "/api/aad-login",
            data={"id_token": id_token},
            content_type="application/json",
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "refresh" not in body["data"]
    assert "access" in body["data"]
    assert body["data"]["username"] == "testuser"
    assert body["data"]["is_active"] is True


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_aad_login_invalid_token_returns_400(api_client, rsa_key_pair):
    with patch("core.users.features.auth.aad_login.service._jwks_client") as MockClient:
        mock_client_instance = MagicMock()
        mock_client_instance.get_signing_key_from_jwt.side_effect = jwt.InvalidTokenError("bad token")
        MockClient.return_value = mock_client_instance

        resp = await api_client.post(
            "/api/aad-login",
            data={"id_token": "not.a.valid.token"},
            content_type="application/json",
        )

    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "invalid_sso_token"
    assert body["error"]["message"] == "Microsoft Token is invalid or expired"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_aad_login_user_not_found_returns_400(api_client, rsa_key_pair):
    id_token = make_test_id_token(rsa_key_pair, username="ghostuser")

    mock_signing_key = MagicMock()
    mock_signing_key.key = rsa_key_pair.public_key()

    with patch("core.users.features.auth.aad_login.service._jwks_client") as MockClient:
        mock_client_instance = MagicMock()
        mock_client_instance.get_signing_key_from_jwt.return_value = mock_signing_key
        MockClient.return_value = mock_client_instance

        resp = await api_client.post(
            "/api/aad-login",
            data={"id_token": id_token},
            content_type="application/json",
        )

    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "invalid_sso_token"
    assert body["error"]["message"] == "Microsoft Token is invalid or expired"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_aad_login_invalid_challenge_does_not_bind_identity(api_client, user, rsa_key_pair, settings):
    from core.users.models import EntraLoginChallenge

    settings.ENTRA_BIND_BY_USERNAME = True
    user.username = "first-login-user"
    await user.asave()
    invalid_nonce = "synthetic-nonce-not-matching-token"
    challenge = await EntraLoginChallenge.objects.acreate(
        nonce_digest=hashlib.sha256(invalid_nonce.encode()).hexdigest(),
        expires_at=timezone.now() + settings.AAD_LOGIN_CHALLENGE_LIFETIME,
    )
    id_token = make_test_id_token(
        rsa_key_pair,
        username="first-login-user",
        nonce="synthetic-nonce",
    )
    mock_signing_key = MagicMock()
    mock_signing_key.key = rsa_key_pair.public_key()

    with patch("core.users.features.auth.aad_login.service._jwks_client") as MockClient:
        mock_client_instance = MagicMock()
        mock_client_instance.get_signing_key_from_jwt.return_value = mock_signing_key
        MockClient.return_value = mock_client_instance

        response = await api_client.post(
            "/api/aad-login",
            data={"id_token": id_token},
            content_type="application/json",
            headers={"Cookie": f"{settings.AAD_LOGIN_CHALLENGE_COOKIE}={challenge.pk}"},
        )

    assert response.status_code == 401
    assert not await EntraIdentity.objects.filter(user=user).aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_aad_login_missing_id_token_returns_422(api_client):
    resp = await api_client.post(
        "/api/aad-login",
        data={},
        content_type="application/json",
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_failed"
    assert any(error["field"] == "id_token" for error in body["error"]["details"])
