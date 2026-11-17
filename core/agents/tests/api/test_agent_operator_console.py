"""Operator console reads: list filters, derived health, grant history and grant revocation."""

import itertools
import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.agents.models import AgentIdentity, EnrollmentGrant
from core.agents.queries import AgentHealth, agent_health
from core.labs.models import EquipmentCategory, EquipmentKind
from core.users.models import URSGroup
from tests.factories import create_computing_equipment

_URS_IDS = itertools.count(82000)


def _user(username: str, role: str):
    user = get_user_model().objects.create_user(username=username, password="password")
    group, _ = Group.objects.get_or_create(name=f"console-{role}-{username}")
    URSGroup.objects.create(group=group, urs_group_id=next(_URS_IDS), labs_role=role)
    user.groups.add(group)
    return user


@pytest.fixture
def coordinator(db):
    return _user("console-coord", "coord")


@pytest.fixture
def viewer(db):
    return _user("console-viewer", "user")


@pytest.fixture
def client(coordinator):
    api = APIClient()
    api.force_authenticate(user=coordinator)
    return api


def _computer(name: str):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    kind = EquipmentKind.objects.create(category=category, name=f"Computer-{uuid.uuid4()}")
    return create_computing_equipment(sku=f"CONSOLE-{uuid.uuid4()}", kind=kind, name=name)


def _issue(client, equipment) -> dict:
    resp = client.post("/api/agents", {"equipment_uid": str(equipment.uid)}, format="json")
    assert resp.status_code == 201, resp.data
    return resp.data["data"]


@pytest.mark.django_db
def test_list_filters_by_equipment_ids_uid_and_state(client):
    first, second, third = _computer("one"), _computer("two"), _computer("three")
    for equipment in (first, second, third):
        _issue(client, equipment)
    AgentIdentity.objects.filter(equipment=third).update(state=AgentIdentity.State.REVOKED)

    by_ids = client.get(f"/api/agents?equipment={first.pk},{second.pk}")
    assert by_ids.status_code == 200
    assert {row["equipment"]["id"] for row in by_ids.data["data"]} == {first.pk, second.pk}

    by_uid = client.get(f"/api/agents?equipment_uid={third.uid}")
    assert [row["equipment"]["id"] for row in by_uid.data["data"]] == [third.pk]

    pending = client.get(f"/api/agents?equipment={first.pk},{third.pk}&state=pending")
    assert [row["equipment"]["id"] for row in pending.data["data"]] == [first.pk]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query", ["equipment=abc", "equipment=0", "equipment=1,,x", "state=paused", "equipment_uid=x"]
)
def test_list_rejects_invalid_filters(client, query):
    resp = client.get(f"/api/agents?{query}")
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "invalid_request"


@pytest.mark.django_db
def test_list_rejects_more_than_100_equipment_ids(client):
    ids = ",".join(str(n) for n in range(1, 102))
    assert client.get(f"/api/agents?equipment={ids}").status_code == 400


@pytest.mark.django_db
@override_settings(AGENT_HEALTH_ONLINE_S=60, AGENT_HEALTH_OFFLINE_S=300)
def test_health_has_three_values_for_active_agents_only():
    now = timezone.now()
    identity = AgentIdentity(state=AgentIdentity.State.ACTIVE)
    assert agent_health(identity, now=now) == AgentHealth.OFFLINE  # never sent a heartbeat
    identity.last_seen_at = now - timedelta(seconds=60)
    assert agent_health(identity, now=now) == AgentHealth.ONLINE
    identity.last_seen_at = now - timedelta(seconds=61)
    assert agent_health(identity, now=now) == AgentHealth.DELAYED
    identity.last_seen_at = now - timedelta(seconds=301)
    assert agent_health(identity, now=now) == AgentHealth.OFFLINE
    for state in (AgentIdentity.State.PENDING, AgentIdentity.State.REVOKED, AgentIdentity.State.DECOMMISSIONED):
        identity.state = state
        assert agent_health(identity, now=now) is None


@pytest.mark.django_db
def test_detail_health_is_null_until_enrolled_then_a_choice(client):
    issued = _issue(client, _computer("health"))
    agent = AgentIdentity.objects.get(agent_uid=issued["agent_uid"])
    assert client.get(f"/api/agents/{agent.pk}").data["data"]["health"] is None
    AgentIdentity.objects.filter(pk=agent.pk).update(
        state=AgentIdentity.State.ACTIVE, public_key="k", public_key_sha256="h", last_seen_at=timezone.now()
    )
    assert client.get(f"/api/agents/{agent.pk}").data["data"]["health"] == {"value": "online", "label": "Online"}


@pytest.mark.django_db
def test_grant_history_lists_metadata_without_the_secret(client, coordinator):
    issued = _issue(client, _computer("history"))
    agent = AgentIdentity.objects.get(agent_uid=issued["agent_uid"])
    assert client.post(f"/api/agents/{agent.pk}/enrollment-grants", {}, format="json").status_code == 201

    resp = client.get(f"/api/agents/{agent.pk}/enrollment-grants")
    assert resp.status_code == 200
    rows = resp.data["data"]
    assert [row["status"]["value"] for row in rows] == ["usable", "revoked"]
    assert rows[0]["created_by"]["username"] == coordinator.username
    assert resp.data["meta"]["pagination"]["count"] == 2
    for row in rows:
        assert "grant" not in row and "token_hash" not in row
        assert issued["grant"] not in str(row)


@pytest.mark.django_db
def test_grant_history_marks_expired_grants(client):
    issued = _issue(client, _computer("expired"))
    agent = AgentIdentity.objects.get(agent_uid=issued["agent_uid"])
    EnrollmentGrant.objects.filter(agent=agent).update(expires_at=timezone.now() - timedelta(seconds=1))
    rows = client.get(f"/api/agents/{agent.pk}/enrollment-grants").data["data"]
    assert rows[0]["status"]["value"] == "expired"


@pytest.mark.django_db
def test_grant_history_of_unknown_agent_is_404(client):
    assert client.get("/api/agents/999999/enrollment-grants").status_code == 404


@pytest.mark.django_db
def test_revoking_the_last_grant_retires_the_pending_agent_and_is_idempotent(client):
    equipment = _computer("revoke")
    issued = _issue(client, equipment)
    agent = AgentIdentity.objects.get(agent_uid=issued["agent_uid"])
    grant = agent.enrollment_grants.get()
    path = f"/api/agents/{agent.pk}/enrollment-grants/{grant.pk}/actions/revoke"

    first = client.post(path)
    assert first.status_code == 200
    assert first.data["data"]["status"]["value"] == "revoked"
    agent.refresh_from_db()
    assert agent.state == AgentIdentity.State.REVOKED

    again = client.post(path)
    assert again.status_code == 200
    assert again.data["data"]["revoked_at"] == first.data["data"]["revoked_at"]
    # The computer is free for a new enrollment.
    _issue(client, equipment)


@pytest.mark.django_db
def test_revoke_grant_of_another_agent_is_404(client):
    one = AgentIdentity.objects.get(agent_uid=_issue(client, _computer("a"))["agent_uid"])
    other = AgentIdentity.objects.get(agent_uid=_issue(client, _computer("b"))["agent_uid"])
    grant = other.enrollment_grants.get()
    resp = client.post(f"/api/agents/{one.pk}/enrollment-grants/{grant.pk}/actions/revoke")
    assert resp.status_code == 404
    grant.refresh_from_db()
    assert grant.revoked_at is None


@pytest.mark.django_db
def test_revoke_redeemed_grant_is_409(client):
    agent = AgentIdentity.objects.get(agent_uid=_issue(client, _computer("used"))["agent_uid"])
    grant = agent.enrollment_grants.get()
    EnrollmentGrant.objects.filter(pk=grant.pk).update(used_at=timezone.now())
    resp = client.post(f"/api/agents/{agent.pk}/enrollment-grants/{grant.pk}/actions/revoke")
    assert resp.status_code == 409
    assert resp.data["error"]["code"] == "grant_redeemed"


@pytest.mark.django_db
def test_grant_revoke_requires_coordinator(client, viewer):
    agent = AgentIdentity.objects.get(agent_uid=_issue(client, _computer("perm"))["agent_uid"])
    grant = agent.enrollment_grants.get()
    client.force_authenticate(user=viewer)
    assert client.get(f"/api/agents/{agent.pk}/enrollment-grants").status_code == 200
    assert client.post(f"/api/agents/{agent.pk}/enrollment-grants/{grant.pk}/actions/revoke").status_code == 403
    grant.refresh_from_db()
    assert grant.revoked_at is None
