"""PATCH /agent/equipment/activity: an agent reports the live activity of its own computer."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.agents.application import transition_agent_state
from core.agents.models import AgentIdentity
from core.agents.tests.api.test_agent_request_signature import _clear_nonce_cache, enrolled  # noqa: F401
from core.agents.tests.signing import signed_headers
from core.labs.models import ComputingActivity, Equipment
from tests.factories import create_computing_equipment

ACTIVITY = "/agent/equipment/activity"


def report(identity, key, payload, *, path=ACTIVITY):
    body = json.dumps(payload).encode()
    headers = signed_headers(key, identity.agent_uid, body, method="PATCH", path=path)
    return APIClient().patch(ACTIVITY, data=body, content_type="application/json", **headers)


def test_report_updates_the_agents_own_computer(enrolled):  # noqa: F811
    identity, key, _ = enrolled
    response = report(identity, key, {"status": "active", "remote_user": "alice", "booking_code": "BK-1"})

    assert response.status_code == 200, response.json()
    data = response.json()["data"]
    assert data["status"]["value"] == "active" and data["remote_user"] == "alice"
    activity = ComputingActivity.objects.get(computing_id=identity.equipment_id)
    assert activity.booking_code == "BK-1"
    assert activity.last_agent_report_at is not None


def test_repeated_inactive_report_keeps_inactive_at_and_refreshes_report_time(enrolled):  # noqa: F811
    identity, key, _ = enrolled
    assert report(identity, key, {"status": "inactive"}).status_code == 200
    activity = ComputingActivity.objects.get(computing_id=identity.equipment_id)
    inactive_at = activity.inactive_at
    stale = activity.last_agent_report_at - timedelta(minutes=1)
    ComputingActivity.objects.filter(pk=activity.pk).update(last_agent_report_at=stale)

    assert report(identity, key, {"status": "inactive"}).status_code == 200
    activity.refresh_from_db()
    assert activity.inactive_at == inactive_at and activity.last_agent_report_at > stale


def test_the_request_cannot_name_another_computer(enrolled):  # noqa: F811
    identity, key, _ = enrolled
    other = create_computing_equipment(sku="ACT-OTHER", name="Other", kind=identity.equipment.kind)

    for field in ("equipment_id", "computing_id", "sku"):
        response = report(identity, key, {"status": "free", field: other.pk})
        assert response.status_code == 422, field
    assert not ComputingActivity.objects.filter(computing=other).exists()


@pytest.mark.parametrize(
    "payload",
    [{"status": "exploded"}, {"offline_at": "2026-01-01T00:00:00Z"}, {"last_agent_report_at": "2026-01-01T00:00Z"}],
)
def test_invalid_or_server_managed_fields_are_refused(enrolled, payload):  # noqa: F811
    identity, key, _ = enrolled
    response = report(identity, key, payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert not ComputingActivity.objects.filter(computing_id=identity.equipment_id).exists()


def test_unsigned_operator_and_revoked_requests_are_rejected(enrolled):  # noqa: F811
    from rest_framework_simplejwt.tokens import RefreshToken

    identity, key, actor = enrolled
    body = b'{"status": "free"}'
    assert APIClient().patch(ACTIVITY, data=body, content_type="application/json").status_code == 401
    operator = APIClient()
    operator.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(actor).access_token}")
    assert operator.patch(ACTIVITY, data=body, content_type="application/json").status_code == 401

    transition_agent_state(identity.agent_uid, AgentIdentity.State.REVOKED, actor=actor)
    assert report(identity, key, {"status": "free"}).status_code == 401
    assert not ComputingActivity.objects.filter(computing_id=identity.equipment_id).exists()


def test_signature_for_another_path_is_rejected(enrolled):  # noqa: F811
    identity, key, _ = enrolled
    assert report(identity, key, {"status": "free"}, path="/agent/heartbeat").status_code == 401


def test_deleted_computer_is_a_conflict(enrolled):  # noqa: F811
    identity, key, _ = enrolled
    Equipment.objects.filter(pk=identity.equipment_id).update(deleted_at=timezone.now())
    response = report(identity, key, {"status": "free"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "equipment_unavailable"
