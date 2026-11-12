"""Entra access tokens for the desktop audit tool on the endpoints that opt in."""

import time
import uuid
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings as django_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from core.users.models import EntraIdentity
from tests.factories import BenchFactory, UserFactory, create_computing_equipment, grant_labs_role

CATALOG = "/api/labs/audit-catalog"
JWKS = "core.users.features.auth.access_token._jwks_client"


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def jwks(signing_key):
    key = MagicMock()
    key.key = signing_key.public_key()
    with patch(JWKS) as client:
        client.return_value.get_signing_key_from_jwt.return_value = key
        yield client


@pytest.fixture
def coordinator(db):
    user = grant_labs_role(UserFactory(username="scanner_coord", email="scanner_coord@example.com"), "coord")
    EntraIdentity.objects.create(user=user, tenant_id=uuid.UUID(django_settings.AAD_TENANT_ID), object_id=uuid.uuid4())
    return user


def _token(key, user=None, **overrides):
    now = int(time.time())
    claims = {
        "iss": f"https://login.microsoftonline.com/{django_settings.AAD_TENANT_ID}/v2.0",
        "aud": f"api://{django_settings.AAD_AUDIENCE}",
        "tid": django_settings.AAD_TENANT_ID,
        "oid": str(user.entra_identity.object_id) if user else str(uuid.uuid4()),
        "scp": "LabMango.Audit",
        "iat": now,
        "nbf": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    claims = {name: value for name, value in claims.items() if value is not None}
    return jwt.encode(claims, key, algorithm="RS256")


def _client(token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.mark.django_db
class TestEntraAccessToken:
    def test_valid_token_reads_catalog(self, jwks, signing_key, coordinator):
        assert _client(_token(signing_key, coordinator)).get(CATALOG).status_code == 200

    def test_v1_issuer_is_accepted(self, jwks, signing_key, coordinator):
        token = _token(signing_key, coordinator, iss=f"https://sts.windows.net/{django_settings.AAD_TENANT_ID}/")

        assert _client(token).get(CATALOG).status_code == 200

    def test_records_audit_as_the_bound_user(self, jwks, signing_key, coordinator):
        bench = BenchFactory(sku="SCAN-BENCH-1")

        response = _client(_token(signing_key, coordinator)).post(
            f"/api/labs/resources/uid/{bench.uid}/audits",
            {"result": "PASS"},
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )

        assert response.status_code == 201
        assert response.json()["data"]["auditor"]["id"] == coordinator.id

    def test_missing_scope_is_forbidden(self, jwks, signing_key, coordinator):
        assert _client(_token(signing_key, coordinator, scp="User.Read")).get(CATALOG).status_code == 403

    def test_app_only_token_is_forbidden(self, jwks, signing_key, coordinator):
        token = _token(signing_key, coordinator, scp=None, roles=["LabMango.Audit"], idtyp="app")

        assert _client(token).get(CATALOG).status_code == 403

    @pytest.mark.parametrize(
        "overrides",
        [
            {"aud": "api://someone-else"},
            {"exp": int(time.time()) - 3600},
            {"tid": str(uuid.uuid4())},
            {"oid": None},
        ],
    )
    def test_invalid_claims_are_unauthorized(self, jwks, signing_key, coordinator, overrides):
        assert _client(_token(signing_key, coordinator, **overrides)).get(CATALOG).status_code == 401

    def test_wrong_signing_key_is_unauthorized(self, jwks, coordinator):
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        assert _client(_token(other_key, coordinator)).get(CATALOG).status_code == 401

    def test_unbound_subject_is_unauthorized(self, jwks, signing_key, db):
        assert _client(_token(signing_key)).get(CATALOG).status_code == 401

    def test_inactive_user_is_unauthorized(self, jwks, signing_key, coordinator):
        coordinator.is_active = False
        coordinator.save(update_fields=["is_active"])

        assert _client(_token(signing_key, coordinator)).get(CATALOG).status_code == 401

    def test_bound_user_without_labs_role_is_forbidden(self, jwks, signing_key, db):
        user = UserFactory(username="scanner_plain", email="scanner_plain@example.com")
        EntraIdentity.objects.create(
            user=user, tenant_id=uuid.UUID(django_settings.AAD_TENANT_ID), object_id=uuid.uuid4()
        )

        assert _client(_token(signing_key, user)).get(CATALOG).status_code == 403

    def test_jwks_outage_is_unavailable(self, signing_key, coordinator):
        with patch(JWKS) as client:
            client.return_value.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientConnectionError("down")

            assert _client(_token(signing_key, coordinator)).get(CATALOG).status_code == 503

    def test_disabled_setting_ignores_entra_tokens(self, jwks, signing_key, coordinator, settings):
        settings.ENTRA_API_ACCESS_TOKENS_ENABLED = False

        assert _client(_token(signing_key, coordinator)).get(CATALOG).status_code == 401

    def test_lab_mango_jwt_still_works(self, coordinator):
        token = AccessToken.for_user(coordinator)

        assert _client(str(token)).get(CATALOG).status_code == 200

    def test_equipment_uid_detail_is_read_only_for_entra_tokens(self, jwks, signing_key, coordinator):
        equipment = create_computing_equipment(sku="SCAN-EQ-1", name="Scanner equipment")
        client = _client(_token(signing_key, coordinator))

        assert client.get(f"/api/labs/equipment/uid/{equipment.uid}").status_code == 200
        assert (
            client.patch(f"/api/labs/equipment/uid/{equipment.uid}", {"name": "Changed"}, format="json").status_code
            == 401
        )
        equipment.refresh_from_db()
        assert equipment.name == "Scanner equipment"

    def test_other_endpoints_do_not_accept_entra_tokens(self, jwks, signing_key, coordinator):
        assert _client(_token(signing_key, coordinator)).get("/api/labs/audits").status_code == 401
