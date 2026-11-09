"""Signed device requests: POST /agent/heartbeat accepts only the enrolled key's signature."""

import hashlib
import json
import secrets
import time
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient

from core.agents.application import (
    ENROLLMENT_CONTEXT,
    EnrollAgentInput,
    create_enrollment_grant,
    enroll_agent,
    transition_agent_state,
)
from core.agents.contracts import CreateEnrollmentGrantInput
from core.agents.models import AgentIdentity
from core.agents.tests.signing import b64url, signed_headers
from core.labs.models import ComputingEquipment, EquipmentCategory, EquipmentKind

HEARTBEAT = "/agent/heartbeat"


@pytest.fixture(autouse=True)
def _clear_nonce_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def enrolled(db):
    """An ACTIVE agent identity and the device private key that enrolled it."""
    actor = get_user_model().objects.create_user(username="sig-operator", password="unused")
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    kind = EquipmentKind.objects.create(category=category, name=f"Computer-{uuid.uuid4()}")
    equipment = ComputingEquipment.objects.create(sku=f"SIG-{uuid.uuid4()}", kind=kind, name="Signed host")
    issued = create_enrollment_grant(
        CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=10), actor=actor
    )

    private_key = Ed25519PrivateKey.generate()
    der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER, format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    proof_message = b"\0".join(
        (
            ENROLLMENT_CONTEXT,
            settings.BACKEND_ID.encode("ascii"),
            str(issued.agent_uid).encode("ascii"),
            hashlib.sha256(issued.grant.encode()).hexdigest().encode("ascii"),
            der,
        )
    )
    identity = enroll_agent(
        EnrollAgentInput(
            grant=issued.grant,
            public_key=b64url(der),
            key_storage="software",
            fingerprint="",
            agent_version="1.0.0",
            proof=b64url(private_key.sign(proof_message)),
        )
    )
    return identity, private_key, actor


def post_heartbeat(body: bytes, headers: dict[str, str]):
    return APIClient().post(HEARTBEAT, data=body, content_type="application/json", **headers)


def assert_unauthenticated(response):
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert response["WWW-Authenticate"] == "LabMango-Agent-Signature"


def test_signed_heartbeat_records_liveness(enrolled):
    identity, key, _ = enrolled
    body = json.dumps({"agent_uid": str(identity.agent_uid)}).encode()

    response = post_heartbeat(body, signed_headers(key, identity.agent_uid, body))

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"
    identity.refresh_from_db()
    assert identity.last_seen_at is not None


def test_heartbeat_body_may_omit_agent_uid(enrolled):
    identity, key, _ = enrolled
    body = b"{}"
    assert post_heartbeat(body, signed_headers(key, identity.agent_uid, body)).status_code == 200


def test_unsigned_heartbeat_naming_a_real_agent_is_rejected(enrolled):
    identity, _key, _ = enrolled
    body = json.dumps({"agent_uid": str(identity.agent_uid)}).encode()

    assert_unauthenticated(post_heartbeat(body, {}))
    identity.refresh_from_db()
    assert identity.last_seen_at is None


def test_signature_from_another_key_is_rejected(enrolled):
    identity, _key, _ = enrolled
    body = b"{}"
    assert_unauthenticated(
        post_heartbeat(body, signed_headers(Ed25519PrivateKey.generate(), identity.agent_uid, body))
    )


@pytest.mark.parametrize(
    "mutation",
    ["body", "path", "method"],
)
def test_signature_binds_body_path_and_method(enrolled, mutation):
    identity, key, _ = enrolled
    body = b"{}"
    kwargs = {}
    signed_body = body
    if mutation == "body":
        signed_body = b'{"other": 1}'
    elif mutation == "path":
        kwargs["path"] = "/agent/enrollments"
    else:
        kwargs["method"] = "PUT"
    headers = signed_headers(key, identity.agent_uid, signed_body, **kwargs)
    assert_unauthenticated(post_heartbeat(body, headers))


def test_stale_and_future_timestamps_are_rejected(enrolled, settings):
    identity, key, _ = enrolled
    settings.AGENT_REQUEST_MAX_SKEW_S = 60
    body = b"{}"
    now = int(time.time())
    assert_unauthenticated(post_heartbeat(body, signed_headers(key, identity.agent_uid, body, timestamp=now - 120)))
    assert_unauthenticated(post_heartbeat(body, signed_headers(key, identity.agent_uid, body, timestamp=now + 120)))


def test_replayed_nonce_is_rejected(enrolled):
    identity, key, _ = enrolled
    body = b"{}"
    headers = signed_headers(key, identity.agent_uid, body)

    assert post_heartbeat(body, headers).status_code == 200
    assert_unauthenticated(post_heartbeat(body, headers))


def test_forged_request_does_not_consume_the_nonce(enrolled):
    identity, key, _ = enrolled
    body = b"{}"
    nonce = b64url(secrets.token_bytes(16))
    forged = signed_headers(Ed25519PrivateKey.generate(), identity.agent_uid, body, nonce=nonce)
    assert_unauthenticated(post_heartbeat(body, forged))

    assert post_heartbeat(body, signed_headers(key, identity.agent_uid, body, nonce=nonce)).status_code == 200


def test_short_nonce_is_rejected(enrolled):
    identity, key, _ = enrolled
    body = b"{}"
    headers = signed_headers(key, identity.agent_uid, body, nonce=b64url(b"short"))
    assert_unauthenticated(post_heartbeat(body, headers))


def test_revoked_agent_is_denied_on_the_next_request(enrolled):
    identity, key, actor = enrolled
    body = b"{}"
    assert post_heartbeat(body, signed_headers(key, identity.agent_uid, body)).status_code == 200

    transition_agent_state(identity.agent_uid, AgentIdentity.State.REVOKED, actor=actor)

    assert_unauthenticated(post_heartbeat(body, signed_headers(key, identity.agent_uid, body)))


def test_body_agent_uid_must_match_signed_identity(enrolled):
    identity, key, _ = enrolled
    body = json.dumps({"agent_uid": str(uuid.uuid4())}).encode()

    response = post_heartbeat(body, signed_headers(key, identity.agent_uid, body))

    assert response.status_code == 400


def test_operator_token_cannot_send_agent_heartbeat(enrolled):
    from rest_framework_simplejwt.tokens import RefreshToken

    identity, _key, actor = enrolled
    token = str(RefreshToken.for_user(actor).access_token)
    response = APIClient().post(
        HEARTBEAT,
        {"agent_uid": str(identity.agent_uid)},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert_unauthenticated(response)
