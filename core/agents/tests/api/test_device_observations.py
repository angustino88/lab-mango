"""Signed ingestion, isolation and credential lifecycle for attached hardware."""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from django.db import close_old_connections
from django.utils import timezone
from rest_framework.test import APIClient

from core.agents.application import ReportDeviceObservationsInput, issue_grant_for_agent, transition_agent_state
from core.agents.application import report_device_observations as execute_observations
from core.agents.exceptions import AgentRequestUnauthenticated
from core.agents.models import AgentIdentity
from core.agents.tests.signing import signed_headers
from core.labs.features.monitoring.contracts import DeviceObservation, DeviceObservationInput
from core.labs.features.monitoring.queries.connections import list_device_connections
from core.labs.models.monitoring import DeviceConnection, DeviceObservationBatch, MonitoringEvent

ROOT = "/agent/device-observations/actions/report"
_GENERATE_KEY = object()


def generation_key(identity):
    return identity.monitoring_generation_key


def report_device_observations(identity, values, *, batch_key):
    command = ReportDeviceObservationsInput(
        identity,
        DeviceObservationInput(
            computing_id=identity.equipment_id, agent_key=str(identity.agent_uid), batch_key=batch_key, **values
        ),
    )
    return execute_observations(command, actor=identity)


def send_raw(identity, key, body, *, batch_key=_GENERATE_KEY, query=""):
    headers: dict[str, Any] = signed_headers(key, identity.agent_uid, body, method="POST", path=ROOT)
    if batch_key is _GENERATE_KEY:
        batch_key = uuid.uuid4()
    if batch_key is not None:
        headers["HTTP_IDEMPOTENCY_KEY"] = str(batch_key)
    return APIClient().post(ROOT + query, data=body, content_type="application/json", **headers)


def send(identity, key, payload, *, batch_key=_GENERATE_KEY, query=""):
    return send_raw(identity, key, json.dumps(payload).encode(), batch_key=batch_key, query=query)


def assert_error(response, status, code):
    assert response.status_code == status, response.data
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["details"], list)
    assert isinstance(error["request_id"], str) and error["request_id"]
    return error


def payload(identity, **changes):
    return {
        "generation_key": str(generation_key(identity)),
        "collector_key": "usb",
        "sequence": 1,
        "collected_at": timezone.now().isoformat(),
        "is_complete": True,
        "devices": [{"observation_key": "usb:1", "name": "Probe", "interface_name": "USB", "state": "connected"}],
        **changes,
    }


def test_signed_report_is_idempotent_and_listed_only_for_own_computing(enrolled):
    identity, key, _ = enrolled
    client = APIClient()
    policy_headers: dict[str, Any] = signed_headers(
        key, identity.agent_uid, b"", method="GET", path="/agent/monitoring-policy"
    )
    policy = client.get("/agent/monitoring-policy", **policy_headers)
    assert policy.status_code == 200, policy.data
    assert policy.data["data"]["generation_key"] == str(generation_key(identity))
    data, batch_key = payload(identity), uuid.uuid4()
    first = send(identity, key, data, batch_key=batch_key)
    assert first.status_code == 200, first.data
    replay = send(identity, key, data, batch_key=batch_key)
    assert replay.status_code == 200 and replay.data == first.data
    assert replay["Idempotency-Replayed"] == "true"
    assert DeviceConnection.objects.get().computing_id == identity.equipment_id
    assert DeviceObservationBatch.objects.count() == MonitoringEvent.objects.count() == 1
    changed = send(identity, key, {**data, "sequence": 2}, batch_key=batch_key)
    assert changed.status_code == 422 and changed.data["error"]["code"] == "idempotency_key_reuse"


@pytest.mark.parametrize("field", ["computing_id", "agent_id", "equipment_id", "last_seen_at"])
def test_foreign_identity_and_server_fields_are_rejected(enrolled, field):
    identity, key, _ = enrolled
    response = send(identity, key, payload(identity, **{field: 123}))
    assert response.status_code == 422 and response.data["error"]["code"] == "validation_failed"
    assert not DeviceConnection.objects.exists()


def test_nested_unknown_duplicate_and_oversized_reports_are_rejected(enrolled):
    identity, key, _ = enrolled
    data = payload(identity)
    data["devices"][0]["equipment_id"] = 123
    assert send(identity, key, data).status_code == 422
    data = payload(identity)
    data["devices"] *= 2
    assert send(identity, key, data).status_code == 422
    assert send(identity, key, payload(identity, padding="x" * 262144)).status_code == 413
    assert not DeviceConnection.objects.exists()


@pytest.mark.parametrize(
    "batch_key,code",
    [
        (None, "idempotency_key_required"),
        ("not-a-uuid", "invalid_idempotency_key"),
        ("a" * 65, "invalid_idempotency_key"),
    ],
)
def test_missing_and_malformed_idempotency_headers_are_bad_requests(enrolled, batch_key, code):
    identity, key, _ = enrolled
    assert_error(send(identity, key, payload(identity), batch_key=batch_key), 400, code)
    assert not DeviceObservationBatch.objects.exists()


def test_bare_array_is_a_malformed_request_instead_of_semantic_validation(enrolled):
    identity, key, _ = enrolled
    assert_error(send(identity, key, []), 400, "malformed_request")
    assert not DeviceObservationBatch.objects.exists()


@pytest.mark.parametrize("nested", [False, True])
def test_duplicate_json_object_keys_are_rejected_before_ingestion(enrolled, nested):
    identity, key, _ = enrolled
    raw = json.dumps(payload(identity))
    if nested:
        raw = raw.replace('"name": "Probe"', '"name": "Probe", "name": "Changed"')
    else:
        raw = raw.replace('"sequence": 1', '"sequence": 1, "sequence": 2')
    assert_error(send_raw(identity, key, raw.encode()), 400, "malformed_request")
    assert not DeviceObservationBatch.objects.exists()


def test_naive_collection_timestamp_names_its_invalid_format(enrolled):
    identity, key, _ = enrolled
    response = send(identity, key, payload(identity, collected_at="2026-01-01T10:00:00"))
    error = assert_error(response, 422, "validation_failed")
    assert any(detail["field"] == "collected_at" and detail["code"] == "invalid_format" for detail in error["details"])
    assert not DeviceObservationBatch.objects.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("sequence", True),
        ("sequence", "1"),
        ("sequence", 1.0),
        ("is_complete", "true"),
        ("is_complete", 1),
        ("collector_key", 1),
    ],
)
def test_wire_types_are_strict_and_never_coerced(enrolled, field, value):
    identity, key, _ = enrolled
    assert_error(send(identity, key, payload(identity, **{field: value})), 422, "validation_failed")
    assert not DeviceObservationBatch.objects.exists()


@pytest.mark.parametrize(
    "field,value", [("observation_key", 1), ("name", 42), ("serial_number", True), ("interface_name", 1)]
)
def test_nested_device_wire_types_are_strict(enrolled, field, value):
    identity, key, _ = enrolled
    data = payload(identity)
    data["devices"][0][field] = value
    assert_error(send(identity, key, data), 422, "validation_failed")
    assert not DeviceObservationBatch.objects.exists()


@pytest.mark.parametrize("query", ["?unknown=value", "?%75nknown=value"])
def test_post_rejects_unknown_query_parameters_including_encoded_names(enrolled, query):
    identity, key, _ = enrolled
    assert_error(send(identity, key, payload(identity), query=query), 400, "invalid_query")
    assert not DeviceObservationBatch.objects.exists()


@pytest.mark.parametrize("query", ["?unknown=value", "?%75nknown=value"])
def test_policy_rejects_unknown_query_parameters_including_encoded_names(enrolled, query):
    identity, key, _ = enrolled
    path = "/agent/monitoring-policy"
    headers: dict[str, Any] = signed_headers(key, identity.agent_uid, b"", method="GET", path=path)
    assert_error(APIClient().get(path + query, **headers), 400, "invalid_query")


def test_unsigned_and_revoked_agents_cannot_report(enrolled):
    identity, key, actor = enrolled
    response = APIClient().post(ROOT, payload(identity), format="json")
    assert response.status_code == 401
    assert send(identity, key, payload(identity)).status_code == 200
    transition_agent_state(identity.agent_uid, AgentIdentity.State.REVOKED, actor=actor)
    assert list_device_connections(computing_id=identity.equipment_id).get().freshness == "unknown"
    assert send(identity, key, payload(identity, sequence=2)).status_code == 401
    assert DeviceObservationBatch.objects.count() == 1


def test_recovery_invalidates_observations_and_stale_authentication_is_fenced(enrolled):
    identity, key, actor = enrolled
    assert send(identity, key, payload(identity)).status_code == 200
    issue_grant_for_agent(identity.pk, 10, actor=actor)
    assert list_device_connections(computing_id=identity.equipment_id).get().freshness == "unknown"
    values = {
        **payload(identity),
        "generation_key": generation_key(identity),
        "collected_at": timezone.now(),
        "devices": (DeviceObservation("usb:1", "USB", "connected"),),
    }
    with pytest.raises(AgentRequestUnauthenticated):
        report_device_observations(identity, values, batch_key=uuid.uuid4())


def test_generation_rejects_key_rotation_even_when_old_authentication_succeeded(enrolled):
    identity, _, _ = enrolled
    AgentIdentity.objects.filter(pk=identity.pk).update(public_key_sha256="f" * 64)
    with pytest.raises(AgentRequestUnauthenticated):
        report_device_observations(
            identity,
            {
                **payload(identity),
                "generation_key": generation_key(identity),
                "collected_at": timezone.now(),
                "devices": (),
            },
            batch_key=uuid.uuid4(),
        )


@pytest.mark.django_db(transaction=True)
def test_revocation_racing_a_report_cannot_leave_current_connections(enrolled):
    identity, _, actor = enrolled
    barrier = Barrier(2)
    values = {
        **payload(identity),
        "generation_key": generation_key(identity),
        "collected_at": timezone.now(),
        "devices": (DeviceObservation("usb:1", "USB", "connected"),),
    }

    def report():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                report_device_observations(identity, values, batch_key=uuid.uuid4())
                return "accepted"
            except AgentRequestUnauthenticated:
                return "revoked"
        finally:
            close_old_connections()

    def revoke():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            transition_agent_state(identity.agent_uid, AgentIdentity.State.REVOKED, actor=actor)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        reported = executor.submit(report)
        revoked = executor.submit(revoke)
        assert reported.result(timeout=20) in {"accepted", "revoked"}
        revoked.result(timeout=20)
    assert all(row.freshness == "unknown" for row in list_device_connections(computing_id=identity.equipment_id))
