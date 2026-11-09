import json
import uuid
from unittest.mock import Mock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from core.routing.models import RoutingChange, RoutingEntity, SyncState

VALID_STATIC_TOKEN = "test-sync-token-256bits-long-valid-base64url"
DATA_HASH = "43f154ed4a9512251f4b2bf1e0588c167a2ac83c224de4f4bcc28adf2d720fd5"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_headers():
    return {
        "HTTP_AUTHORIZATION": f"Bearer {VALID_STATIC_TOKEN}",
        "HTTP_X_REQUEST_ID": "0123456789abcdef0123456789abcdef",
    }


@pytest.fixture
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.mark.django_db
def test_get_only_guarantees(api_client, auth_headers):
    # GET succeeds
    resp = api_client.get("/internal/info", **auth_headers)
    assert resp.status_code == 200

    # Non-GET methods return 405 with Allow: GET
    for method_name in ("post", "put", "patch", "delete", "options"):
        method = getattr(api_client, method_name)
        resp = method("/internal/info", **auth_headers)
        assert resp.status_code == 405
        assert resp["Allow"] == "GET"
        assert resp.data["error"]["code"] == "method_not_allowed"

    # GET with request body returns 400 invalid_request
    resp = api_client.generic(
        "GET",
        "/internal/info",
        data=json.dumps({"unexpected": "body"}),
        content_type="application/json",
        **auth_headers,
    )
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "invalid_request"


@pytest.mark.django_db
def test_safe_and_side_effect_free(api_client, auth_headers):
    """GET-2: assert no database write queries are performed."""
    with CaptureQueriesContext(connection) as queries:
        resp = api_client.get("/internal/info", **auth_headers)
        assert resp.status_code == 200

    write_verbs = ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER")
    write_queries = [q["sql"] for q in queries if any(q["sql"].strip().upper().startswith(verb) for verb in write_verbs)]
    assert not write_queries, f"DB write queries executed: {write_queries}"


@pytest.mark.django_db
def test_headers_and_correlation(api_client, auth_headers):
    # Valid 32-hex request ID is echoed
    resp = api_client.get("/internal/info", **auth_headers)
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/json"
    assert resp["Cache-Control"] == "no-store"
    assert resp["X-Request-ID"] == "0123456789abcdef0123456789abcdef"
    assert "error" not in resp.data

    # Missing request ID is generated
    resp = api_client.get("/internal/info", HTTP_AUTHORIZATION=f"Bearer {VALID_STATIC_TOKEN}")
    assert resp.status_code == 200
    assert len(resp["X-Request-ID"]) == 32

    # Wrong case alias X-Request-Id is ignored and a new one generated
    resp = api_client.get(
        "/internal/info",
        HTTP_AUTHORIZATION=f"Bearer {VALID_STATIC_TOKEN}",
        HTTP_X_REQUEST_ID_ALIAS="not_recognized",
    )
    assert resp.status_code == 200
    assert len(resp["X-Request-ID"]) == 32


@pytest.mark.django_db
def test_strict_query_parameters(api_client, auth_headers):
    # Unknown query param on info -> 400 invalid_query
    resp = api_client.get("/internal/info?unknown_param=1", **auth_headers)
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "invalid_query"
    assert resp.data["error"]["details"][0]["field"] == "unknown_param"

    # Repeated query param on snapshot -> 400 invalid_query
    resp = api_client.get("/internal/snapshot/users?limit=10&limit=20", **auth_headers)
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "invalid_query"
    assert resp.data["error"]["details"][0]["field"] == "limit"

    # Empty query param on snapshot -> 400 invalid_query
    resp = api_client.get("/internal/snapshot/users?limit=", **auth_headers)
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "invalid_query"
    assert resp.data["error"]["details"][0]["field"] == "limit"

    # Limit out of bounds on snapshot
    resp = api_client.get("/internal/snapshot/users?limit=10000", **auth_headers)
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "invalid_query"

    # Missing since or epoch on changes
    resp = api_client.get("/internal/changes/users", **auth_headers)
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "invalid_query"


@pytest.mark.django_db
def test_entity_validation(api_client, auth_headers):
    # Unsupported entities return 404 entity_not_supported
    for entity in ("equipment", "agent_keys", "nonexistent"):
        resp = api_client.get(f"/internal/snapshot/{entity}", **auth_headers)
        assert resp.status_code == 404
        assert resp.data["error"]["code"] == "entity_not_supported"

        resp = api_client.get(f"/internal/changes/{entity}?since=0&epoch={uuid.uuid4()}", **auth_headers)
        assert resp.status_code == 404
        assert resp.data["error"]["code"] == "entity_not_supported"

        resp = api_client.get(f"/internal/digest/{entity}", **auth_headers)
        assert resp.status_code == 404
        assert resp.data["error"]["code"] == "entity_not_supported"


@pytest.mark.django_db
def test_authentication_method_b_and_failures(api_client):
    # 1. Missing Authorization header -> 401
    resp = api_client.get("/internal/info")
    assert resp.status_code == 401
    assert resp["WWW-Authenticate"] == "Bearer"
    assert resp.data["error"]["code"] == "unauthorized"

    # 2. Malformed Authorization header -> 401
    resp = api_client.get("/internal/info", HTTP_AUTHORIZATION="Basic 12345")
    assert resp.status_code == 401
    assert resp.data["error"]["code"] == "unauthorized"

    # 3. Invalid bearer token -> 401
    resp = api_client.get("/internal/info", HTTP_AUTHORIZATION="Bearer invalid-token")
    assert resp.status_code == 401
    assert resp.data["error"]["code"] == "unauthorized"

    # 4. Valid static token -> 200
    resp = api_client.get("/internal/info", HTTP_AUTHORIZATION=f"Bearer {VALID_STATIC_TOKEN}")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_authentication_method_a_entra(api_client, rsa_keypair):
    private_key, public_key = rsa_keypair
    tenant_id = "0ae51e19-07c8-4e4b-bb6d-648ee58410f4"
    audience = "api://labmango-dept_a"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"

    mock_client = Mock()
    mock_signing_key = Mock()
    mock_signing_key.key = public_key
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key

    with patch("core.routing.api.authentication._get_jwks_client", return_value=mock_client):
        # 1. Valid application-only token with Routing.Sync.Read
        now = int(timezone.now().timestamp())
        valid_payload = {
            "iss": issuer,
            "aud": audience,
            "exp": now + 3600,
            "nbf": now - 10,
            "idtyp": "app",
            "roles": ["Routing.Sync.Read"],
        }
        token = jwt.encode(valid_payload, private_key, algorithm="RS256", headers={"kid": "test-kid"})
        resp = api_client.get("/internal/info", HTTP_AUTHORIZATION=f"Bearer {token}")
        assert resp.status_code == 200

        # 2. Token missing required role -> 403 forbidden
        bad_role_payload = dict(valid_payload, roles=["Other.Role"])
        token = jwt.encode(bad_role_payload, private_key, algorithm="RS256", headers={"kid": "test-kid"})
        resp = api_client.get("/internal/info", HTTP_AUTHORIZATION=f"Bearer {token}")
        assert resp.status_code == 403
        assert resp.data["error"]["code"] == "forbidden"

        # 3. Delegated user token (with scp claim) -> 403 forbidden
        user_payload = dict(valid_payload, scp="User.Read")
        token = jwt.encode(user_payload, private_key, algorithm="RS256", headers={"kid": "test-kid"})
        resp = api_client.get("/internal/info", HTTP_AUTHORIZATION=f"Bearer {token}")
        assert resp.status_code == 403
        assert resp.data["error"]["code"] == "forbidden"

        # 4. Token with wrong audience -> 401 unauthorized
        wrong_aud_payload = dict(valid_payload, aud="api://wrong-backend")
        token = jwt.encode(wrong_aud_payload, private_key, algorithm="RS256", headers={"kid": "test-kid"})
        resp = api_client.get("/internal/info", HTTP_AUTHORIZATION=f"Bearer {token}")
        assert resp.status_code == 401
        assert resp.data["error"]["code"] == "unauthorized"

        # 5. Token with wrong issuer -> 401 unauthorized
        wrong_iss_payload = dict(valid_payload, iss="https://login.microsoftonline.com/wrong-tenant/v2.0")
        token = jwt.encode(wrong_iss_payload, private_key, algorithm="RS256", headers={"kid": "test-kid"})
        resp = api_client.get("/internal/info", HTTP_AUTHORIZATION=f"Bearer {token}")
        assert resp.status_code == 401
        assert resp.data["error"]["code"] == "unauthorized"

        # 6. Expired token -> 401 unauthorized
        expired_payload = dict(valid_payload, exp=now - 100, nbf=now - 200)
        token = jwt.encode(expired_payload, private_key, algorithm="RS256", headers={"kid": "test-kid"})
        resp = api_client.get("/internal/info", HTTP_AUTHORIZATION=f"Bearer {token}")
        assert resp.status_code == 401
        assert resp.data["error"]["code"] == "unauthorized"


@pytest.mark.django_db
def test_jwks_unavailable_returns_503(api_client, rsa_keypair):
    private_key, _ = rsa_keypair
    token = jwt.encode(
        {"iss": "test", "aud": "test", "exp": 9999999999},
        private_key,
        algorithm="RS256",
        headers={"kid": "test-kid"},
    )
    mock_client = Mock()
    mock_client.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientConnectionError("Connection timed out")

    with patch("core.routing.api.authentication._get_jwks_client", return_value=mock_client):
        resp = api_client.get("/internal/info", HTTP_AUTHORIZATION=f"Bearer {token}")
        assert resp.status_code == 503
        assert resp.data["error"]["code"] == "unavailable"


@pytest.mark.django_db
def test_snapshot_and_changes_endpoints(api_client, auth_headers):
    epoch = uuid.UUID("5f0c2d1e-0b57-4c1e-9d65-3a1e8f5d7a10")
    SyncState.objects.create(entity_type="users", version=2, epoch=epoch)
    key1 = "entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000001"
    key2 = "entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000002"

    RoutingEntity.objects.create(entity_type="users", key=key1, version=1, state="active", data={}, data_hash=DATA_HASH)
    RoutingEntity.objects.create(entity_type="users", key=key2, version=2, state="active", data={}, data_hash=DATA_HASH)
    RoutingChange.objects.create(entity_type="users", version=1, key=key1, op="upsert", state="active", data={}, data_hash=DATA_HASH)
    RoutingChange.objects.create(entity_type="users", version=2, key=key2, op="upsert", state="active", data={}, data_hash=DATA_HASH)

    # 1. Snapshot
    snap_resp = api_client.get("/internal/snapshot/users?limit=1", **auth_headers)
    assert snap_resp.status_code == 200
    assert snap_resp.data["data"]["head_version"] == 2
    assert snap_resp.data["data"]["epoch"] == str(epoch)
    assert len(snap_resp.data["data"]["items"]) == 1
    assert snap_resp.data["data"]["next_after"] == key1

    # 2. Changes delta
    chg_resp = api_client.get(f"/internal/changes/users?since=0&epoch={epoch}", **auth_headers)
    assert chg_resp.status_code == 200
    assert chg_resp.data["data"]["mode"] == "delta"
    assert len(chg_resp.data["data"]["changes"]) == 2

    # 3. Changes reset on epoch mismatch
    wrong_epoch = uuid.UUID("00000000-0000-0000-0000-000000000000")
    reset_resp = api_client.get(f"/internal/changes/users?since=0&epoch={wrong_epoch}", **auth_headers)
    assert reset_resp.status_code == 200
    assert reset_resp.data["data"]["mode"] == "reset"
    assert reset_resp.data["data"]["reason"] == "epoch_changed"

    # 4. Digest
    digest_resp = api_client.get("/internal/digest/users", **auth_headers)
    assert digest_resp.status_code == 200
    assert digest_resp.data["data"]["count"] == 2
    assert digest_resp.data["data"]["checksum"] == "sha256:e55f21dda5b3742e8baa44eeadfb712312907f2226c940cdb9dc843b5dce5a13"


@pytest.mark.django_db
def test_credential_isolation(api_client):
    """AUTH-3: Sync credentials must not authenticate normal /api/* routes."""
    resp = api_client.get("/api/labs/benches", HTTP_AUTHORIZATION=f"Bearer {VALID_STATIC_TOKEN}")
    assert resp.status_code == 401
