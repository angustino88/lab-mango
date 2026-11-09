"""Agent lifecycle fixes: recovery routing, key reuse, stranded-pending cleanup, errors and paging."""

import hashlib
import itertools
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from core.agents.application import (
    ENROLLMENT_CONTEXT,
    EnrollAgentInput,
    create_enrollment_grant,
    enroll_agent,
    issue_grant_for_agent,
)
from core.agents.contracts import CreateEnrollmentGrantInput
from core.agents.exceptions import AgentEnrollmentConflict
from core.agents.models import AgentIdentity, EnrollmentGrant
from core.agents.tests.signing import b64url, signed_headers
from core.labs.models import ComputingEquipment, EquipmentCategory, EquipmentKind
from core.routing.models import RoutingEntity
from core.users.models import URSGroup

_URS_IDS = itertools.count(82000)


@pytest.fixture
def coordinator(db):
    user = get_user_model().objects.create_user(username="lifecycle-coord", password="unused")
    group = Group.objects.create(name="lifecycle-coord")
    URSGroup.objects.create(group=group, urs_group_id=next(_URS_IDS), labs_role="coord")
    user.groups.add(group)
    return user


@pytest.fixture
def equipment(db):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    kind = EquipmentKind.objects.create(category=category, name=f"Computer-{uuid.uuid4()}")
    return ComputingEquipment.objects.create(sku=f"LC-{uuid.uuid4()}", kind=kind, name="Lifecycle host")


def _enroll(grant: str, agent_uid, private_key: Ed25519PrivateKey) -> AgentIdentity:
    der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER, format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    message = b"\0".join(
        (
            ENROLLMENT_CONTEXT,
            settings.BACKEND_ID.encode("ascii"),
            str(agent_uid).encode("ascii"),
            hashlib.sha256(grant.encode()).hexdigest().encode("ascii"),
            der,
        )
    )
    return enroll_agent(
        EnrollAgentInput(
            grant=grant,
            public_key=b64url(der),
            key_storage="software",
            fingerprint="",
            agent_version="1.0.0",
            proof=b64url(private_key.sign(message)),
        )
    )


def _live_route(agent_uid) -> bool:
    return RoutingEntity.objects.filter(entity_type="agents", key=str(agent_uid), deleted_at__isnull=True).exists()


def test_recovery_grant_for_active_agent_tombstones_route_and_denies_old_key(coordinator, equipment):
    cache.clear()
    issued = create_enrollment_grant(CreateEnrollmentGrantInput(equipment.uid, 10), actor=coordinator)
    key = Ed25519PrivateKey.generate()
    identity = _enroll(issued.grant, issued.agent_uid, key)
    assert _live_route(identity.agent_uid)

    issue_grant_for_agent(identity.pk, 10, actor=coordinator)

    identity.refresh_from_db()
    assert identity.state == AgentIdentity.State.PENDING
    assert not _live_route(identity.agent_uid)
    body = b"{}"
    response = APIClient().post(
        "/agent/heartbeat", data=body, content_type="application/json", **signed_headers(key, identity.agent_uid, body)
    )
    assert response.status_code == 401


def test_recovery_may_reenroll_the_same_device_key(coordinator, equipment):
    issued = create_enrollment_grant(CreateEnrollmentGrantInput(equipment.uid, 10), actor=coordinator)
    key = Ed25519PrivateKey.generate()
    identity = _enroll(issued.grant, issued.agent_uid, key)

    recovery = issue_grant_for_agent(identity.pk, 10, actor=coordinator)
    reenrolled = _enroll(recovery.grant, recovery.agent_uid, key)

    assert reenrolled.pk == identity.pk
    assert reenrolled.state == AgentIdentity.State.ACTIVE
    assert _live_route(identity.agent_uid)


def test_key_of_another_identity_is_still_rejected(coordinator, equipment):
    issued = create_enrollment_grant(CreateEnrollmentGrantInput(equipment.uid, 10), actor=coordinator)
    key = Ed25519PrivateKey.generate()
    _enroll(issued.grant, issued.agent_uid, key)

    other_kind = EquipmentKind.objects.create(category=equipment.kind.category, name=f"Other-{uuid.uuid4()}")
    other = ComputingEquipment.objects.create(sku=f"LC-{uuid.uuid4()}", kind=other_kind, name="Other host")
    second = create_enrollment_grant(CreateEnrollmentGrantInput(other.uid, 10), actor=coordinator)
    with pytest.raises(AgentEnrollmentConflict):
        _enroll(second.grant, second.agent_uid, key)


def test_pending_identity_with_a_fresh_grant_is_not_revoked_by_cleanup(coordinator, equipment):
    issued = create_enrollment_grant(CreateEnrollmentGrantInput(equipment.uid, 10), actor=coordinator)
    identity = AgentIdentity.objects.get(agent_uid=issued.agent_uid)
    # An older, expired grant sits next to the fresh one.
    EnrollmentGrant(
        agent=identity, token_hash=hashlib.sha256(b"old").hexdigest(), expires_at=timezone.now() - timedelta(minutes=1)
    ).save(actor=coordinator)

    with pytest.raises(AgentEnrollmentConflict):
        create_enrollment_grant(CreateEnrollmentGrantInput(equipment.uid, 10), actor=coordinator)

    identity.refresh_from_db()
    assert identity.state == AgentIdentity.State.PENDING


def test_pending_identity_with_only_expired_grants_is_replaced(coordinator, equipment):
    issued = create_enrollment_grant(CreateEnrollmentGrantInput(equipment.uid, 10), actor=coordinator)
    EnrollmentGrant.objects.filter(agent__agent_uid=issued.agent_uid).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )

    replacement = create_enrollment_grant(CreateEnrollmentGrantInput(equipment.uid, 10), actor=coordinator)

    assert AgentIdentity.objects.get(agent_uid=issued.agent_uid).state == AgentIdentity.State.REVOKED
    assert AgentIdentity.objects.get(agent_uid=replacement.agent_uid).state == AgentIdentity.State.PENDING


def test_grant_for_missing_equipment_is_404(coordinator):
    client = APIClient()
    client.force_authenticate(user=coordinator)
    response = client.post("/api/agents", {"equipment_uid": str(uuid.uuid4())}, format="json")
    assert response.status_code == 404
    assert response.data["error"]["code"] == "equipment_not_found"


def test_unexpected_enrollment_error_does_not_leak_details(db):
    with patch("core.agents.api.views.enroll_agent", side_effect=RuntimeError("dsn=postgres://secret")):
        response = APIClient().post(
            "/agent/enrollments",
            {
                "grant": "eg_x",
                "public_key": "AA",
                "key_storage": "software",
                "agent_version": "1.0.0",
                "proof": "AA",
            },
            format="json",
        )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.content.decode()


def test_agent_list_is_paginated_and_bounded(coordinator, equipment):
    create_enrollment_grant(CreateEnrollmentGrantInput(equipment.uid, 10), actor=coordinator)
    client = APIClient()
    client.force_authenticate(user=coordinator)

    response = client.get("/api/agents", {"page_size": 1})
    assert response.status_code == 200
    assert len(response.data["data"]) == 1
    assert response.data["meta"]["pagination"]["count"] == 1
    assert response.data["meta"]["pagination"]["page_size"] == 1

    assert client.get("/api/agents", {"page_size": 101}).status_code == 400
