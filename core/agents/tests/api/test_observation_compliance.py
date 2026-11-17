"""Independent wire-contract and scope acceptance checks for device observations."""

import json
import re
from typing import Any

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.agents.exceptions import AgentRequestUnauthenticated
from core.agents.tests.api.test_device_observations import ROOT as REPORT
from core.agents.tests.api.test_device_observations import assert_error, payload, send, send_raw
from core.agents.tests.signing import signed_headers
from core.common.contracts import ActorContext
from core.common.domain.errors import Forbidden
from core.labs.features.monitoring.application.observe_devices import (
    InvalidateDeviceConnectionsInput,
    invalidate_device_connections,
)
from core.labs.models import Equipment, EquipmentInterface
from core.labs.models.monitoring import DeviceConnection, DeviceObservationBatch, DeviceObservationCursor

POLICY = "/agent/monitoring-policy"
UTC_MICROSECONDS = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z"


def policy(identity, key, *, query="", **headers):
    signing_headers: dict[str, Any] = signed_headers(key, identity.agent_uid, b"", method="GET", path=POLICY)
    return APIClient().get(POLICY + query, **signing_headers, **headers)


@pytest.mark.parametrize(
    "header,code",
    [
        (None, "idempotency_key_required"),
        ("", "invalid_idempotency_key"),
        ("not-a-uuid", "invalid_idempotency_key"),
        ("a" * 65, "invalid_idempotency_key"),
    ],
)
def test_idempotency_header_failures_are_distinct_bad_requests(enrolled, header, code):
    identity, key, _ = enrolled
    response = send(identity, key, payload(identity), batch_key=header)
    assert_error(response, 400, code)
    assert response["Cache-Control"] == "no-store"
    assert not DeviceObservationBatch.objects.exists()


@pytest.mark.parametrize("body", [b"[]", b"null", b"17", b'{"value": NaN}', b"\xef\xbb\xbf{}", b'{"name":"\\ud800"}'])
def test_non_object_or_ambiguous_json_is_rejected_before_writes(enrolled, body):
    identity, key, _ = enrolled
    assert_error(send_raw(identity, key, body), 400, "malformed_request")
    assert not DeviceObservationBatch.objects.exists()


@pytest.mark.parametrize("kind", ["duplicate", "depth", "keys"])
def test_structural_json_limits_precede_semantic_validation(enrolled, kind):
    identity, key, _ = enrolled
    if kind == "duplicate":
        body = json.dumps(payload(identity)).replace('"sequence": 1', '"sequence": 2, "sequence": 1').encode()
    elif kind == "depth":
        nested: dict[str, object] = {}
        for _ in range(33):
            nested = {"child": nested}
        body = json.dumps(nested).encode()
    else:
        body = json.dumps({f"field_{index}": index for index in range(1001)}).encode()
    assert_error(send_raw(identity, key, body), 400, "malformed_request")
    assert not DeviceObservationBatch.objects.exists()


def test_declared_oversize_is_refused_before_body_read_or_authentication(db):
    response = APIClient().post(
        "/agent/device-observations/actions/report", b"{}", content_type="application/json", CONTENT_LENGTH="262145"
    )
    assert_error(response, 413, "payload_too_large")
    assert getattr(response.wsgi_request, "_read_started") is False
    assert response["Cache-Control"] == "no-store"
    assert not DeviceObservationBatch.objects.exists()


@pytest.mark.parametrize("route", ["report", "policy"])
def test_agent_routes_reject_undeclared_query_parameters(enrolled, route):
    identity, key, _ = enrolled
    response = (
        send(identity, key, payload(identity), query="?unexpected=1")
        if route == "report"
        else policy(identity, key, query="?unexpected=1")
    )
    assert_error(response, 400, "invalid_query")
    assert not DeviceObservationBatch.objects.exists()


def test_signed_policy_get_rejects_a_request_body(enrolled):
    identity, key, _ = enrolled
    body = b"{}"
    signing_headers: dict[str, Any] = signed_headers(key, identity.agent_uid, body, method="GET", path=POLICY)
    response = APIClient().generic(
        "GET", POLICY, body.decode("utf-8"), content_type="application/json", **signing_headers
    )
    assert_error(response, 400, "unexpected_body")
    assert response["Cache-Control"] == "no-store"


@pytest.mark.parametrize("kind", ["charset", "content_encoding"])
def test_unsupported_charset_and_content_encoding_are_media_type_failures(enrolled, kind):
    identity, key, _ = enrolled
    body = json.dumps(payload(identity)).encode()
    signing_headers: dict[str, Any] = signed_headers(key, identity.agent_uid, body, method="POST", path=REPORT)
    signing_headers["HTTP_IDEMPOTENCY_KEY"] = "83114434-22d7-4f92-b5be-1e009e2bd0f6"
    content_type = "application/json"
    if kind == "charset":
        content_type += "; charset=iso-8859-1"
    else:
        signing_headers["HTTP_CONTENT_ENCODING"] = "gzip"
    response = APIClient().post(REPORT, body, content_type=content_type, **signing_headers)
    assert_error(response, 415, "unsupported_media_type")
    assert response["Cache-Control"] == "no-store"
    assert not DeviceObservationBatch.objects.exists()


@pytest.mark.parametrize("value", ["2026-11-17T03:00:00", "2026-13-17T03:00:00Z", "2026-11-17T03:00:00.1234567Z"])
def test_collection_timestamp_requires_valid_rfc3339_and_declared_precision(enrolled, value):
    identity, key, _ = enrolled
    error = assert_error(send(identity, key, payload(identity, collected_at=value)), 422, "validation_failed")
    assert any(detail["field"] == "collected_at" and detail["code"] == "invalid_format" for detail in error["details"])
    assert not DeviceObservationBatch.objects.exists()


@pytest.mark.parametrize(
    "field,value", [("sequence", "1"), ("sequence", 1.0), ("is_complete", 1), ("is_complete", "true")]
)
def test_snapshot_json_types_are_strict_at_http_boundary(enrolled, field, value):
    identity, key, _ = enrolled
    error = assert_error(send(identity, key, payload(identity, **{field: value})), 422, "validation_failed")
    assert any(detail["code"] == "invalid_type" for detail in error["details"])
    assert not DeviceObservationBatch.objects.exists()


def test_uuid_control_characters_and_blank_instance_keys_are_refused(enrolled):
    identity, key, _ = enrolled
    data = payload(identity, generation_key=str(identity.monitoring_generation_key).replace("-", ""))
    error = assert_error(send(identity, key, data), 422, "validation_failed")
    assert any(detail["code"] == "invalid_format" for detail in error["details"])
    data = payload(identity)
    data["devices"][0]["name"] = "Probe\x01"
    error = assert_error(send(identity, key, data), 422, "validation_failed")
    assert any(detail["code"] == "invalid_format" for detail in error["details"])
    data = payload(identity)
    data["devices"][0]["observation_key"] = "   "
    error = assert_error(send(identity, key, data), 422, "validation_failed")
    assert any("observation_key" in detail["field"] for detail in error["details"])
    assert not DeviceObservationBatch.objects.exists()


def test_array_bound_and_validation_error_cap_are_enforced(enrolled):
    identity, key, _ = enrolled
    devices = [
        {"observation_key": f"port-{index}", "interface_name": "USB", "state": "connected"} for index in range(201)
    ]
    error = assert_error(send(identity, key, payload(identity, devices=devices)), 422, "validation_failed")
    assert any(detail["code"] == "max_items" for detail in error["details"])
    data = payload(identity, **{f"unknown_{index}": index for index in range(120)})
    error = assert_error(send(identity, key, data), 422, "validation_failed")
    assert len(error["details"]) == 100
    assert not DeviceObservationBatch.objects.exists()


def test_nested_validation_paths_use_array_brackets(enrolled):
    identity, key, _ = enrolled
    data = payload(identity)
    data["devices"][0]["name"] = 42
    error = assert_error(send(identity, key, data), 422, "validation_failed")
    assert any(
        detail["field"] == "devices[0].name" and detail["code"] == "invalid_type" for detail in error["details"]
    ), error["details"]


def test_text_normalization_preserves_meaningful_whitespace_and_output_time_is_utc(enrolled):
    identity, key, _ = enrolled
    data = payload(identity)
    data["devices"][0]["name"] = " e\u0301 "
    response = send(identity, key, data)
    assert response.status_code == 200, response.data
    assert re.fullmatch(UTC_MICROSECONDS, response.data["data"]["received_at"])
    assert DeviceConnection.objects.get().name == " é "
    assert response["Cache-Control"] == "no-store"


def test_policy_query_budget_cache_and_conditional_get(enrolled, django_assert_num_queries):
    identity, key, _ = enrolled
    for name in ("Review USB", "Review CAN", "Review Ethernet"):
        EquipmentInterface.objects.create(name=name)
    with django_assert_num_queries(2):
        response = policy(identity, key)
    assert response.status_code == 200, response.data
    assert {"Review USB", "Review CAN", "Review Ethernet"} <= set(response.data["data"]["interface_names"])
    etag = response["ETag"]
    assert etag.startswith('"') and etag.endswith('"') and not etag.startswith("W/")
    assert response["Cache-Control"] == "private, no-cache"

    assert {"Accept", "Accept-Language"} <= set(response["Vary"].split(", "))
    with django_assert_num_queries(2):
        unchanged = policy(identity, key, HTTP_IF_NONE_MATCH=etag)
    assert unchanged.status_code == 304 and unchanged.content == b""
    assert unchanged["ETag"] == etag and unchanged["Cache-Control"] == "private, no-cache"


def test_connection_read_keeps_uid_references_utc_and_existing_admin_access(enrolled):
    identity, key, operator = enrolled
    interface = EquipmentInterface.objects.create(name="USB")
    peripheral = Equipment.objects.create(
        sku="COMPLIANCE-PROBE", name="Probe", serial_number="REVIEW-PROBE", kind=identity.equipment.kind
    )
    peripheral.interfaces.add(interface)
    data = payload(identity)
    data["devices"][0]["serial_number"] = peripheral.serial_number
    assert send(identity, key, data).status_code == 200
    operator.is_staff = operator.is_superuser = True
    operator.save(update_fields=("is_staff", "is_superuser"))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(operator).access_token}")
    response = client.get("/api/labs/device-connections", {"computer_id": identity.equipment_id})
    assert response.status_code == 200, response.data
    row = response.data["data"][0]
    assert list(row["computer"]) == ["id", "uid", "name"]
    assert row["equipment"] == {"id": peripheral.pk, "uid": str(peripheral.uid), "name": "Probe"}
    assert row["interface"] == {"id": interface.pk, "name": "USB"}
    assert all(re.fullmatch(UTC_MICROSECONDS, row[field]) for field in ("observed_at", "received_at"))
    assert response["Cache-Control"] == "private, no-cache"

    unexpected_body = client.generic(
        "GET",
        f"/api/labs/device-connections?computer_id={identity.equipment_id}",
        "{}",
        content_type="application/json",
    )
    assert_error(unexpected_body, 400, "unexpected_body")


def test_domain_authentication_failure_retains_uniform_challenge(enrolled, monkeypatch):
    identity, key, _ = enrolled

    def rejected(*args, **kwargs):
        raise AgentRequestUnauthenticated("Agent request authentication failed.")

    monkeypatch.setattr("core.agents.api.observations.report_device_observations", rejected)
    response = send(identity, key, payload(identity))
    assert_error(response, 401, "unauthenticated")
    assert response["WWW-Authenticate"] == "LabMango-Agent-Signature"
    assert response["Cache-Control"] == "no-store"


def test_invalidation_cannot_bypass_scope_or_capability(enrolled):
    identity, key, _ = enrolled
    assert send(identity, key, payload(identity)).status_code == 200
    command = InvalidateDeviceConnectionsInput(identity.equipment_id)
    denied = [
        ActorContext("review", "system", frozenset({"monitoring:invalidate"}), frozenset({identity.equipment_id + 1})),
        ActorContext("review", "system", frozenset(), frozenset({identity.equipment_id})),
    ]
    for actor in denied:
        with pytest.raises(Forbidden):
            invalidate_device_connections(command, actor=actor)
        assert DeviceObservationCursor.objects.get().is_current
