"""Signed gateway intake of telemetry readings over HTTP."""

import json
import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.agents.tests.signing import signed_headers
from core.labs.features.telemetry.public import current_conditions
from core.labs.features.telemetry.tests.test_configuration_api import _approved_profile, _client, _source
from core.labs.models import Room, Station

pytestmark = pytest.mark.django_db
PATH = "/agent/telemetry/samples/bulk"
BASE = "/api/labs/telemetry"


def _post(identity, key, payload):
    body = json.dumps(payload).encode()
    headers = signed_headers(key, identity.agent_uid, body, method="POST", path=PATH)
    return APIClient().post(PATH, data=body, content_type="application/json", **headers)


def test_signed_gateway_submits_readings(enrolled):
    identity, key, _ = enrolled
    coord, admin = _client("http-coord", "coord"), _client("http-admin", "admin")
    room = Room.objects.create(sku="HTTP-R1", name="Room")
    station = Station.objects.create(sku="HTTP-S1", name="Station", room=room)
    gateway = coord.post(
        f"{BASE}/gateways", {"equipment_id": identity.equipment_id, "kind": "room_host"}, format="json"
    )
    assert gateway.status_code == 201, gateway.data
    payload = {"mode": "partial", "operations": []}

    # Registered but not yet covering anything: refused as a whole.
    no_scope = _post(
        identity,
        key,
        {
            **payload,
            "operations": [
                {
                    "data": {
                        "device_uid": "x",
                        "sample_id": str(uuid.uuid4()),
                        "observed_at": timezone.now().isoformat(),
                        "readings": [{"channel_id": 1, "value": "1"}],
                    }
                }
            ],
        },
    )
    assert no_scope.status_code == 409, no_scope.json()

    coord.post(
        f"{BASE}/gateways/{gateway.body['id']}/actions/bind-scope",
        {"target_type": "room", "target_id": room.pk},
        format="json",
    )
    meter = _approved_profile(coord, admin)
    source = _source(coord, installed_at={"type": "station", "id": station.pk}).body
    channel = coord.post(
        f"{BASE}/sources/{source['id']}/channels",
        {"unit_id": 1, "profile_id": meter["id"], "target_type": "station", "target_id": station.pk},
        format="json",
    ).body["channels"][0]

    response = _post(
        identity,
        key,
        {
            "mode": "partial",
            "operations": [
                {
                    "data": {
                        "device_uid": source["device_uid"],
                        "sample_id": str(uuid.uuid4()),
                        "observed_at": timezone.now().isoformat(),
                        "readings": [{"channel_id": channel["id"], "value": "512.5"}],
                    }
                }
            ],
        },
    )
    assert response.status_code == 200, response.json()
    data = response.json()["data"]
    assert data["results"] == [{"status": "accepted", "errors": []}]
    assert data["config_version"] >= 1
    assert current_conditions(station_ids=[station.pk])["stations"][station.pk].power_w == 512.5

    unsigned = APIClient().post(PATH, data=b"{}", content_type="application/json")
    assert unsigned.status_code == 401
    invalid = _post(
        identity,
        key,
        {
            "mode": "partial",
            "operations": [
                {
                    "data": {
                        "device_uid": source["device_uid"],
                        "sample_id": str(uuid.uuid4()),
                        "observed_at": timezone.now().isoformat(),
                        "readings": [{"channel_id": channel["id"], "status": "ok"}],
                    }
                }
            ],
        },
    )
    assert invalid.status_code in (400, 422), invalid.json()
