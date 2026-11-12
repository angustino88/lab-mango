import base64
import hashlib
import itertools
import json
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from core.agents.application import ENROLLMENT_CONTEXT
from core.agents.models import AgentIdentity
from core.agents.tests.signing import signed_headers
from core.labs.models import EquipmentCategory, EquipmentKind
from core.users.models import URSGroup
from tests.factories import create_computing_equipment


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


@pytest.fixture
def api_client():
    return APIClient()


_URS_IDS = itertools.count(81000)


def _user_with_labs_role(username: str, role: str | None):
    user = get_user_model().objects.create_user(username=username, password="password")
    if role is not None:
        group, _ = Group.objects.get_or_create(name=f"agents-{role}-{username}")
        URSGroup.objects.create(group=group, urs_group_id=next(_URS_IDS), labs_role=role)
        user.groups.add(group)
    return user


@pytest.fixture
def admin_user(db):
    # Operator writes need the Labs coordinator role (or admin, which implies it).
    return _user_with_labs_role("agent-admin", "coord")


@pytest.fixture
def plain_user(db):
    return _user_with_labs_role("agent-viewer", "user")


@pytest.fixture
def computing_equipment(db):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing",
        defaults={"name": "Computing", "definition": "Computing", "active": True},
    )
    kind = EquipmentKind.objects.create(category=category, name=f"Computer-{uuid.uuid4()}")
    return create_computing_equipment(sku=f"AGENT-{uuid.uuid4()}", kind=kind, name="Agent host")


@pytest.mark.django_db
def test_operator_routes_require_authentication(api_client, computing_equipment):
    # 1. List
    resp = api_client.get("/api/agents")
    assert resp.status_code == 401

    # 2. Create grant
    resp = api_client.post("/api/agents", {"equipment_uid": str(computing_equipment.uid)})
    assert resp.status_code == 401


@pytest.mark.django_db
def test_operator_writes_require_lab_coordinator_role(api_client, admin_user, plain_user, computing_equipment):
    api_client.force_authenticate(user=admin_user)
    created = api_client.post("/api/agents", {"equipment_uid": str(computing_equipment.uid)}, format="json")
    assert created.status_code == 201
    agent = AgentIdentity.objects.get(agent_uid=created.data["data"]["agent_uid"])

    api_client.force_authenticate(user=plain_user)
    # Reads stay open to any authenticated user.
    assert api_client.get("/api/agents").status_code == 200
    assert api_client.get(f"/api/agents/{agent.pk}").status_code == 200
    # Every write is denied without the coordinator role, and nothing changes.
    for path, body in (
        ("/api/agents", {"equipment_uid": str(computing_equipment.uid)}),
        (f"/api/agents/{agent.pk}/enrollment-grants", {}),
        (f"/api/agents/{agent.pk}/actions/revoke", {}),
        (f"/api/agents/{agent.pk}/actions/decommission", {}),
    ):
        resp = api_client.post(path, body, format="json")
        assert resp.status_code == 403, path
    agent.refresh_from_db()
    assert agent.state == AgentIdentity.State.PENDING
    assert agent.enrollment_grants.count() == 1


@pytest.mark.django_db
def test_lab_admin_role_implies_operator_write_access(api_client, computing_equipment):
    lab_admin = _user_with_labs_role("agent-lab-admin", "admin")
    api_client.force_authenticate(user=lab_admin)
    resp = api_client.post("/api/agents", {"equipment_uid": str(computing_equipment.uid)}, format="json")
    assert resp.status_code == 201


@pytest.mark.django_db
def test_operator_lifecycle_workflow(api_client, admin_user, computing_equipment):
    api_client.force_authenticate(user=admin_user)

    # 1. Create initial enrollment grant
    create_resp = api_client.post(
        "/api/agents",
        {"equipment_uid": str(computing_equipment.uid), "ttl_minutes": 20},
        format="json",
    )
    assert create_resp.status_code == 201
    grant_data = create_resp.data["data"]
    assert grant_data["grant"].startswith("eg_")
    assert grant_data["equipment_uid"] == str(computing_equipment.uid)
    agent_uid = grant_data["agent_uid"]

    agent = AgentIdentity.objects.get(agent_uid=agent_uid)
    assert agent.state == AgentIdentity.State.PENDING

    # 2. List agents
    list_resp = api_client.get("/api/agents")
    assert list_resp.status_code == 200
    assert len(list_resp.data["data"]) >= 1
    assert any(a["agent_uid"] == agent_uid for a in list_resp.data["data"])

    # 3. Retrieve agent detail
    detail_resp = api_client.get(f"/api/agents/{agent.pk}")
    assert detail_resp.status_code == 200
    assert detail_resp.data["data"]["agent_uid"] == agent_uid
    assert detail_resp.data["data"]["state"] == "pending"

    # 4. Issue recovery grant
    grant_resp = api_client.post(f"/api/agents/{agent.pk}/enrollment-grants", {"ttl_minutes": 15}, format="json")
    assert grant_resp.status_code == 201
    assert grant_resp.data["data"]["grant"].startswith("eg_")


@pytest.mark.django_db
def test_agent_info_and_heartbeat(api_client, admin_user, computing_equipment):
    # 1. Agent info
    info_resp = api_client.get("/agent/info")
    assert info_resp.status_code == 200
    assert "capabilities" in info_resp.data["data"]
    assert info_resp.data["data"]["backend_id"] == getattr(settings, "BACKEND_ID", "dept_a")

    # 2. Unsigned heartbeat, even for an unknown agent, is rejected without revealing existence
    hb_resp = api_client.post("/agent/heartbeat", {"agent_uid": str(uuid.uuid4())}, format="json")
    assert hb_resp.status_code == 401


@pytest.mark.django_db
def test_agent_enrollment_and_heartbeat_flow(api_client, admin_user, computing_equipment):
    api_client.force_authenticate(user=admin_user)

    # 1. Operator creates grant
    create_resp = api_client.post(
        "/api/agents",
        {"equipment_uid": str(computing_equipment.uid), "ttl_minutes": 15},
        format="json",
    )
    assert create_resp.status_code == 201
    grant = create_resp.data["data"]["grant"]
    agent_uid = create_resp.data["data"]["agent_uid"]

    # 2. Device generates Ed25519 key pair and proof
    private_key = Ed25519PrivateKey.generate()
    public_key_obj = private_key.public_key()
    der = public_key_obj.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    raw_public_key = _b64(der)
    grant_digest = hashlib.sha256(grant.encode("utf-8")).hexdigest()

    signed_message = b"\0".join(
        (
            ENROLLMENT_CONTEXT,
            settings.BACKEND_ID.encode("ascii"),
            str(agent_uid).encode("ascii"),
            grant_digest.encode("ascii"),
            der,
        )
    )
    proof = _b64(private_key.sign(signed_message))

    # 3. Unauthenticated device enrollment
    api_client.force_authenticate(user=None)
    enroll_payload = {
        "grant": grant,
        "public_key": raw_public_key,
        "key_storage": "software",
        "fingerprint": "device-host-fingerprint",
        "agent_version": "1.0.0",
        "proof": proof,
    }
    enroll_resp = api_client.post("/agent/enrollments", enroll_payload, format="json")
    assert enroll_resp.status_code == 201
    assert enroll_resp.data["data"]["state"] == "active"
    assert enroll_resp.data["data"]["agent_version"] == "1.0.0"

    # 4. Device sends a heartbeat signed with its enrolled key
    hb_body = json.dumps({"agent_uid": agent_uid}).encode()
    hb_resp = api_client.post(
        "/agent/heartbeat",
        data=hb_body,
        content_type="application/json",
        **signed_headers(private_key, agent_uid, hb_body),
    )
    assert hb_resp.status_code == 200
    assert hb_resp.data["data"]["status"] == "ok"
    assert hb_resp.data["data"]["last_seen_at"] is not None

    # 5. Operator revokes agent
    api_client.force_authenticate(user=admin_user)
    agent = AgentIdentity.objects.get(agent_uid=agent_uid)
    revoke_resp = api_client.post(f"/api/agents/{agent.pk}/actions/revoke")
    assert revoke_resp.status_code == 200
    assert revoke_resp.data["data"]["state"] == "revoked"

    # Subsequent signed heartbeat fails because the agent is no longer active
    api_client.force_authenticate(user=None)
    hb_revoked = api_client.post(
        "/agent/heartbeat",
        data=hb_body,
        content_type="application/json",
        **signed_headers(private_key, agent_uid, hb_body),
    )
    assert hb_revoked.status_code == 401
