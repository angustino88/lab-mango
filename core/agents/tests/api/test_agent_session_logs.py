"""POST /agent/session-logs: the agent pushes one completed session after logout."""

import json
import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from core.agents.tests.api.test_agent_request_signature import _clear_nonce_cache, enrolled  # noqa: F401
from core.agents.tests.signing import signed_headers
from core.labs.models import LabSessionLog
from tests.factories import create_computing_equipment

PATH = "/agent/session-logs"


def push(identity, key, payload):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    client = APIClient()
    client.credentials(**signed_headers(key, identity.agent_uid, body, method="POST", path=PATH))
    return client.post(PATH, data=body, content_type="application/json")


def session_payload(**changes: object) -> dict[str, object]:
    now = timezone.now()
    payload = {
        "event_key": "5b0f6c1e-2a7d-4c9e-9a3b-0d6e4f1a2c77",
        "login_at": (now - timedelta(hours=3)).isoformat(),
        "logout_at": (now - timedelta(hours=1)).isoformat(),
        "active_duration_seconds": 5400,
        "remote_user": "nguyen.an",
        "remote_ip": "10.20.4.17",
        "remote_host": "LT-NGUYENAN",
        "booking_code": "BK-7F3K9Q",
        "agent_version": "2.4.1",
    }
    payload.update(changes)
    return {key: value for key, value in payload.items() if value is not ...}


def error_fields(response):
    return {detail["field"] for detail in response.json()["error"]["details"]}


def test_push_stores_session_for_the_agents_computer(enrolled):  # noqa: F811
    identity, key, _ = enrolled
    payload = session_payload()

    response = push(identity, key, payload)

    assert response.status_code == 201, response.json()
    data = response.json()["data"]
    assert data["event_key"] == payload["event_key"] and data["booking_code"] == "BK-7F3K9Q"
    # The enrolled computer stands on no bench, so the code cannot verify.
    assert data["access_type"]["value"] == "unverified_booking"
    stored = LabSessionLog.objects.get(pk=data["id"])
    assert stored.computing_equipment_id == identity.equipment_id
    assert stored.agent_id == str(identity.agent_uid)
    assert stored.creator_id is None


def test_replay_with_same_values_returns_stored_record(enrolled):  # noqa: F811
    identity, key, _ = enrolled
    payload = session_payload()

    first = push(identity, key, payload)
    again = push(identity, key, payload)

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["data"] == first.json()["data"]
    assert LabSessionLog.objects.count() == 1


def test_same_event_id_with_different_values_conflicts(enrolled):  # noqa: F811
    identity, key, _ = enrolled
    push(identity, key, session_payload())

    response = push(identity, key, session_payload(remote_user="someone.else"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_log_conflict"
    assert LabSessionLog.objects.get().remote_user == "nguyen.an"


@pytest.mark.parametrize("code", [None, ""])
def test_temp_login_has_no_booking_code(enrolled, code):  # noqa: F811
    identity, key, _ = enrolled

    response = push(identity, key, session_payload(booking_code=code))

    assert response.status_code == 201, response.json()
    assert response.json()["data"]["booking_code"] is None
    assert response.json()["data"]["access_type"]["value"] == "ad_hoc"


def test_booking_code_may_be_omitted(enrolled):  # noqa: F811
    identity, key, _ = enrolled

    response = push(
        identity, key, session_payload(booking_code=..., remote_ip=..., remote_host=..., agent_version=...)
    )

    assert response.status_code == 201, response.json()


@pytest.mark.parametrize(
    "field",
    ["equipment_id", "computing_equipment", "agent_id", "remote_user_display_name", "host_name", "reported_at"],
)
def test_unknown_fields_are_rejected(enrolled, field):  # noqa: F811
    identity, key, _ = enrolled

    response = push(identity, key, session_payload(**{field: "x"}))

    assert response.status_code == 422
    assert error_fields(response) == {field}
    assert not LabSessionLog.objects.exists()


def test_request_cannot_name_another_computer(enrolled):  # noqa: F811
    identity, key, _ = enrolled
    other = create_computing_equipment(sku="SL-OTHER", name="Other computer")

    response = push(identity, key, session_payload(equipment_id=other.pk))

    assert response.status_code == 422
    assert not LabSessionLog.objects.filter(computing_equipment=other).exists()


@pytest.mark.parametrize("field", ["event_key", "login_at", "logout_at", "active_duration_seconds", "remote_user"])
def test_required_fields(enrolled, field):  # noqa: F811
    identity, key, _ = enrolled

    response = push(identity, key, session_payload(**{field: ...}))

    assert response.status_code == 422
    assert field in error_fields(response)


def test_hard_limits(enrolled):  # noqa: F811
    identity, key, _ = enrolled
    now = timezone.now()
    cases: dict[str, dict[str, object]] = {
        "logout_at": {"logout_at": (now + timedelta(minutes=10)).isoformat()},
        "login_at": {"login_at": (now - timedelta(days=8)).isoformat()},
        "active_duration_seconds": {"active_duration_seconds": 7201},
    }
    for field, changes in cases.items():
        response = push(identity, key, session_payload(event_key=str(uuid.uuid4()), **changes))

        assert response.status_code == 422, field
        assert response.json()["error"]["code"] == "validation_failed"
        assert error_fields(response) == {field}
    assert not LabSessionLog.objects.exists()


def test_non_finite_active_time_is_rejected(enrolled):  # noqa: F811
    identity, key, _ = enrolled
    body = json.dumps(session_payload(active_duration_seconds=float("nan"))).encode()

    response = push(identity, key, body)

    # The strict JSON parser refuses NaN before validation runs.
    assert response.status_code == 400
    assert not LabSessionLog.objects.exists()


def test_body_must_be_an_object(enrolled):  # noqa: F811
    identity, key, _ = enrolled

    response = push(identity, key, [session_payload()])

    assert response.status_code == 400


def test_deleted_computer_is_refused(enrolled):  # noqa: F811
    identity, key, _ = enrolled
    identity.equipment.deleted_at = timezone.now()
    identity.equipment.save(update_fields=["deleted_at"])

    response = push(identity, key, session_payload())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "equipment_unavailable"


@pytest.mark.django_db
def test_unsigned_request_is_rejected():
    response = APIClient().post(PATH, data=session_payload(), format="json")

    assert response.status_code == 401
    assert not LabSessionLog.objects.exists()


@pytest.mark.django_db
def test_a_user_cannot_push_sessions():
    client = APIClient()
    client.force_authenticate(user=get_user_model().objects.create_user(username="not-an-agent", password="x"))

    response = client.post(PATH, data=session_payload(), format="json")

    assert response.status_code in (401, 403)
    assert not LabSessionLog.objects.exists()
