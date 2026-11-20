"""Telemetry configuration over HTTP: the setup flow, access rules, conflicts and idempotency.

Design: docs/proposals/environment-telemetry.md §6-§8 (slice 4).
"""

import itertools
from typing import Any

import pytest
from rest_framework.test import APIClient

from core.labs.models import Room, Station, StationSlot
from core.labs.models.telemetry import ChannelTargetBinding, TelemetryDevice, TelemetryDeviceRole
from core.users.models import User
from tests.factories import BenchFactory, create_computing_equipment, grant_labs_role

pytestmark = pytest.mark.django_db

BASE = "/api/labs/telemetry"
METER_MAP = {"power_w": {"function_code": 3, "register": 0, "words": 2, "type": "float32", "scale": 1}}
PROBE_MAP = {
    "temperature_c": {"function_code": 3, "register": 0, "type": "int16", "scale": 0.1},
    "humidity_percent": {"function_code": 3, "register": 1, "type": "uint16", "scale": 0.1},
}


_ASSETS = itertools.count(1)


def _asset() -> int:
    number = next(_ASSETS)
    return create_computing_equipment(sku=f"TEL-ASSET-{number}", name=f"Asset {number}").pk


class EnvelopeClient(APIClient):
    """Exposes a success payload's `data` envelope as `response.body`."""

    def generic(self, *args, **kwargs) -> Any:
        response: Any = super().generic(*args, **kwargs)
        payload = getattr(response, "data", None)
        response.body = payload.get("data") if isinstance(payload, dict) else payload
        return response


def _client(username: str, role: str | None) -> APIClient:
    user = User.objects.create_user(username=username, display_name=username)
    if role:
        grant_labs_role(user, role)
    client = EnvelopeClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def coord():
    return _client("tel-coord", "coord")


@pytest.fixture
def admin():
    return _client("tel-admin", "admin")


@pytest.fixture
def layout():
    room = Room.objects.create(sku="TEL-API-R3", name="Room 3")
    station = Station.objects.create(sku="TEL-API-SA", name="Station A", room=room)
    other_room = Room.objects.create(sku="TEL-API-R4", name="Room 4")
    return {"room": room, "station": station, "other_room": other_room}


def _approved_profile(coord, admin, key="chint_ddsu666", read_map=METER_MAP) -> Any:
    created = coord.post(
        f"{BASE}/device-profiles", {"key": key, "protocol": "modbus", "read_map": read_map}, format="json"
    )
    assert created.status_code == 201, created.data
    approved = admin.post(f"{BASE}/device-profiles/{created.body['id']}/actions/approve")
    assert approved.status_code == 200, approved.data
    return approved.body


def _source(coord, *, uid="a4-cf-12-9b-00-21", host="192.168.50.21", installed_at) -> Any:
    payload = {
        "kind": "modbus_tcp",
        "device_uid": uid,
        "equipment_id": _asset(),
        "install_location_type": installed_at["type"],
        "install_location_id": installed_at["id"],
        "model": "USR-W630",
        "modbus": {
            "network_host": host,
            "serial_interface": "rs485",
            "baud_rate": 9600,
            "parity": "N",
            "data_bits": 8,
            "stop_bits": 1,
        },
    }
    return coord.post(f"{BASE}/sources", payload, format="json")


def _gateway(coord, room) -> Any:
    gateway = coord.post(f"{BASE}/gateways", {"equipment_id": _asset(), "kind": "room_host"}, format="json")
    assert gateway.status_code == 201, gateway.data
    scope = coord.post(
        f"{BASE}/gateways/{gateway.body['id']}/actions/bind-scope",
        {"target_type": "room", "target_id": room.pk},
        format="json",
    )
    assert scope.status_code == 200, scope.data
    return gateway.body


def test_full_setup_flow_station_and_room_converters(coord, admin, layout):
    meter = _approved_profile(coord, admin)
    probe = _approved_profile(coord, admin, key="es35_sw", read_map=PROBE_MAP)
    gateway = _gateway(coord, layout["room"])
    version_before = TelemetryDevice.objects.get(pk=gateway["id"]).config_version

    station_w630 = _source(coord, installed_at={"type": "station", "id": layout["station"].pk})
    assert station_w630.status_code == 201, station_w630.data
    assert station_w630.body["device_uid"] == "A4:CF:12:9B:00:21"
    assert station_w630.body["room"] == {"id": layout["room"].pk, "name": "Room 3"}
    assert station_w630.body["modbus"]["network_host"] == "192.168.50.21"

    wall_w630 = _source(
        coord, uid="A4:CF:12:9B:00:35", host="192.168.50.22", installed_at={"type": "room", "id": layout["room"].pk}
    )
    assert wall_w630.status_code == 201, wall_w630.data

    channels = coord.post(
        f"{BASE}/sources/{station_w630.body['id']}/channels",
        {"unit_id": 1, "profile_id": meter["id"], "target_type": "station", "target_id": layout["station"].pk},
        format="json",
    )
    assert channels.status_code == 201, channels.data
    probe_channels = coord.post(
        f"{BASE}/sources/{wall_w630.body['id']}/channels",
        {"unit_id": 1, "profile_id": probe["id"], "target_type": "room", "target_id": layout["room"].pk},
        format="json",
    )
    assert probe_channels.status_code == 201, probe_channels.data
    assert sorted(channel["metric"]["id"] for channel in probe_channels.body["channels"]) == [
        "humidity_percent",
        "temperature_c",
    ]
    [power] = channels.body["channels"]
    assert power["unit_id"] == 1 and power["profile"]["name"] == "chint_ddsu666@1"
    assert power["measures"]["target"] == {"type": "station", "id": layout["station"].pk, "name": "Station A"}

    assert TelemetryDevice.objects.get(pk=gateway["id"]).config_version > version_before

    overview = coord.get(f"{BASE}/targets/station/{layout['station'].pk}")
    assert overview.status_code == 200
    assert [device["id"] for device in overview.body["installed_devices"]] == [station_w630.body["id"]]
    assert [channel["id"] for channel in overview.body["channels"]] == [power["id"]]

    listed = coord.get(f"{BASE}/devices", {"room_id": layout["room"].pk})
    assert listed.status_code == 200
    assert {device["id"] for device in listed.body} == {gateway["id"], station_w630.body["id"], wall_w630.body["id"]}


def test_plain_lab_users_and_strangers_are_refused(layout):
    assert _client("tel-user", "user").get(f"{BASE}/devices").status_code == 403
    assert _client("tel-none", None).get(f"{BASE}/devices").status_code == 403


def test_only_lab_admins_approve_profiles(coord, admin):
    created = coord.post(
        f"{BASE}/device-profiles", {"key": "meter", "protocol": "modbus", "read_map": METER_MAP}, format="json"
    )
    refused = coord.post(f"{BASE}/device-profiles/{created.body['id']}/actions/approve")
    assert refused.status_code == 403
    assert refused.data["error"]["code"] == "telemetry_profile_approval_forbidden"
    first = admin.post(f"{BASE}/device-profiles/{created.body['id']}/actions/approve")
    again = admin.post(f"{BASE}/device-profiles/{created.body['id']}/actions/approve")
    assert first.status_code == again.status_code == 200
    assert first.body["approved_at"] == again.body["approved_at"]
    assert first.body["status"]["value"] == "approved"


def test_profile_versions_increase_per_key(coord):
    payload = {"key": "Chint DDSU666", "protocol": "modbus", "read_map": METER_MAP}
    first = coord.post(f"{BASE}/device-profiles", payload, format="json")
    second = coord.post(f"{BASE}/device-profiles", payload, format="json")
    assert (first.body["reference"], second.body["reference"]) == ("chint_ddsu666@1", "chint_ddsu666@2")


def test_profile_read_map_errors_name_the_field(coord):
    bad = {"power_w": {"function_code": 6, "register": 0, "type": "float32"}, "nope": {"function_code": 3}}
    response = coord.post(
        f"{BASE}/device-profiles", {"key": "bad", "protocol": "modbus", "read_map": bad}, format="json"
    )
    assert response.status_code == 422
    fields = {detail["field"] for detail in response.data["error"]["details"]}
    assert {"read_map.power_w.function_code", "read_map.nope"} <= fields


def test_channels_need_an_approved_profile(coord, layout):
    draft = coord.post(
        f"{BASE}/device-profiles", {"key": "m", "protocol": "modbus", "read_map": METER_MAP}, format="json"
    )
    source = _source(coord, installed_at={"type": "station", "id": layout["station"].pk})
    response = coord.post(
        f"{BASE}/sources/{source.body['id']}/channels", {"unit_id": 1, "profile_id": draft.body["id"]}, format="json"
    )
    assert response.status_code == 422
    assert response.data["error"]["code"] == "telemetry_profile_not_approved"


def test_same_unit_and_metric_twice_is_a_conflict(coord, admin, layout):
    meter = _approved_profile(coord, admin)
    source = _source(coord, installed_at={"type": "station", "id": layout["station"].pk})
    url = f"{BASE}/sources/{source.body['id']}/channels"
    assert coord.post(url, {"unit_id": 1, "profile_id": meter["id"]}, format="json").status_code == 201
    again = coord.post(url, {"unit_id": 1, "profile_id": meter["id"]}, format="json")
    assert again.status_code == 409
    assert again.data["error"]["code"] == "telemetry_channel_address_in_use"


def test_network_address_is_unique_until_the_device_retires(coord, layout):
    station = {"type": "station", "id": layout["station"].pk}
    first = _source(coord, installed_at=station)
    clash = _source(coord, uid="A4:CF:12:9B:00:99", installed_at=station)
    assert clash.status_code == 409
    assert clash.data["error"]["code"] == "telemetry_modbus_address_in_use"

    retired = coord.post(f"{BASE}/devices/{first.body['id']}/actions/retire")
    assert retired.status_code == 200 and retired.body["state"]["value"] == "retired"
    assert retired.body["modbus"] is None
    assert coord.post(f"{BASE}/devices/{first.body['id']}/actions/retire").status_code == 200
    assert _source(coord, uid="A4:CF:12:9B:00:99", installed_at=station).status_code == 201


def test_same_device_uid_cannot_register_twice(coord, layout):
    station = {"type": "station", "id": layout["station"].pk}
    _source(coord, installed_at=station)
    again = _source(coord, uid="A4CF129B0021", host="192.168.50.30", installed_at=station)
    assert again.status_code == 409
    assert again.data["error"]["code"] == "telemetry_device_already_registered"


def test_measured_target_must_be_in_the_install_room(coord, admin, layout):
    meter = _approved_profile(coord, admin)
    source = _source(coord, installed_at={"type": "station", "id": layout["station"].pk})
    response = coord.post(
        f"{BASE}/sources/{source.body['id']}/channels",
        {"unit_id": 1, "profile_id": meter["id"], "target_type": "room", "target_id": layout["other_room"].pk},
        format="json",
    )
    assert response.status_code == 422
    assert response.data["error"]["code"] == "telemetry_target_outside_install_room"


def test_unplaced_targets_cannot_host_devices(coord):
    bench: Any = BenchFactory()
    response = _source(coord, installed_at={"type": "bench", "id": bench.pk})
    assert response.status_code == 422
    assert response.data["error"]["code"] == "telemetry_target_not_located"


def test_unknown_target_is_not_found(coord):
    response = _source(coord, installed_at={"type": "room", "id": 999999})
    assert response.status_code == 404
    assert response.data["error"]["code"] == "telemetry_target_not_found"


def test_modbus_settings_are_validated_field_by_field(coord, layout):
    payload = {
        "kind": "modbus_tcp",
        "device_uid": "A4:CF:12:9B:00:21",
        "equipment_id": _asset(),
        "install_location_type": "station",
        "install_location_id": layout["station"].pk,
        "modbus": {"network_host": "not a host!", "serial_interface": "rs485", "baud_rate": 9600, "parity": "N"},
    }
    response = coord.post(f"{BASE}/sources", payload, format="json")
    assert response.status_code == 422
    fields = {detail["field"] for detail in response.data["error"]["details"]}
    assert {"modbus.network_host", "modbus.data_bits", "modbus.stop_bits"} <= fields


def test_one_room_gateway_per_room_and_scope_type_must_fit(coord, layout):
    _gateway(coord, layout["room"])
    second = coord.post(f"{BASE}/gateways", {"equipment_id": _asset(), "kind": "room_host"}, format="json")
    taken = coord.post(
        f"{BASE}/gateways/{second.body['id']}/actions/bind-scope",
        {"target_type": "room", "target_id": layout["room"].pk},
        format="json",
    )
    assert taken.status_code == 409
    assert taken.data["error"]["code"] == "telemetry_room_gateway_exists"
    wrong_type = coord.post(
        f"{BASE}/gateways/{second.body['id']}/actions/bind-scope",
        {"target_type": "station", "target_id": layout["station"].pk},
        format="json",
    )
    assert wrong_type.status_code == 422
    assert wrong_type.data["error"]["code"] == "telemetry_gateway_scope_type_mismatch"


def test_gateway_registration_and_scope_are_idempotent(coord, layout):
    equipment_id = _asset()
    first = coord.post(f"{BASE}/gateways", {"equipment_id": equipment_id, "kind": "room_host"}, format="json")
    again = coord.post(f"{BASE}/gateways", {"equipment_id": equipment_id, "kind": "room_host"}, format="json")
    assert first.body["id"] == again.body["id"]
    url = f"{BASE}/gateways/{first.body['id']}/actions/bind-scope"
    body = {"target_type": "room", "target_id": layout["room"].pk}
    one, two = coord.post(url, body, format="json"), coord.post(url, body, format="json")
    assert one.body == two.body


def test_rebinding_and_unbinding_keep_history(coord, admin, layout):
    meter = _approved_profile(coord, admin)
    source = _source(coord, installed_at={"type": "station", "id": layout["station"].pk})
    created = coord.post(
        f"{BASE}/sources/{source.body['id']}/channels", {"unit_id": 1, "profile_id": meter["id"]}, format="json"
    )
    channel_id = created.body["channels"][0]["id"]
    assert created.body["channels"][0]["measures"] is None

    bind = f"{BASE}/channels/{channel_id}/actions/bind-target"
    assert (
        coord.post(bind, {"target_type": "station", "target_id": layout["station"].pk}, format="json").status_code
        == 200
    )
    moved = coord.post(bind, {"target_type": "room", "target_id": layout["room"].pk}, format="json")
    assert moved.body["measures"]["target"]["type"] == "room"
    unbound = coord.post(f"{BASE}/channels/{channel_id}/actions/unbind")
    assert unbound.body["measures"] is None
    assert ChannelTargetBinding.objects.filter(channel_id=channel_id).count() == 2
    assert not ChannelTargetBinding.objects.filter(channel_id=channel_id, valid_to__isnull=True).exists()


def test_moving_a_source_out_of_its_room_needs_unbound_channels(coord, admin, layout):
    meter = _approved_profile(coord, admin)
    source = _source(coord, installed_at={"type": "station", "id": layout["station"].pk})
    coord.post(
        f"{BASE}/sources/{source.body['id']}/channels",
        {"unit_id": 1, "profile_id": meter["id"], "target_type": "station", "target_id": layout["station"].pk},
        format="json",
    )
    response = coord.patch(
        f"{BASE}/sources/{source.body['id']}",
        {"install_location_type": "room", "install_location_id": layout["other_room"].pk},
        format="json",
    )
    assert response.status_code == 409
    assert response.data["error"]["code"] == "telemetry_channels_still_bound"
    renamed = coord.patch(f"{BASE}/sources/{source.body['id']}", {"model": "USR-W630 v2"}, format="json")
    assert renamed.status_code == 200 and renamed.body["model"] == "USR-W630 v2"


def test_channel_update_and_field_device_link(coord, admin, layout):
    meter = _approved_profile(coord, admin)
    source = _source(coord, installed_at={"type": "station", "id": layout["station"].pk})
    created = coord.post(
        f"{BASE}/sources/{source.body['id']}/channels", {"unit_id": 1, "profile_id": meter["id"]}, format="json"
    )
    url = f"{BASE}/channels/{created.body['channels'][0]['id']}"
    asset_id = _asset()
    updated = coord.patch(
        url, {"label": "Main feed", "is_enabled": False, "field_device_equipment_id": asset_id}, format="json"
    )
    assert updated.status_code == 200, updated.data
    assert (updated.body["label"], updated.body["is_enabled"], updated.body["field_device"]["id"]) == (
        "Main feed",
        False,
        asset_id,
    )
    cleared = coord.patch(url, {"field_device_equipment_id": None}, format="json")
    assert cleared.body["field_device"] is None and cleared.body["label"] == "Main feed"


def test_discovered_source_is_claimed(coord, layout):
    discovered = TelemetryDevice.objects.create(
        role=TelemetryDeviceRole.SOURCE, kind="modbus_tcp", device_uid="A4:CF:12:9B:00:77"
    )
    response = coord.post(
        f"{BASE}/devices/{discovered.pk}/actions/claim",
        {
            "equipment_id": _asset(),
            "install_location_type": "room",
            "install_location_id": layout["room"].pk,
            "modbus": {"network_host": "192.168.50.40"},
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.body["state"]["value"] == "claimed"
    assert (
        coord.post(
            f"{BASE}/devices/{discovered.pk}/actions/claim",
            {
                "equipment_id": _asset(),
                "install_location_type": "room",
                "install_location_id": layout["room"].pk,
                "modbus": {"network_host": "192.168.50.41"},
            },
            format="json",
        ).status_code
        == 409
    )


def test_device_list_query_count_is_constant(coord, layout, django_assert_max_num_queries):
    station = {"type": "station", "id": layout["station"].pk}
    _gateway(coord, layout["room"])
    for index in range(5):
        _source(coord, uid=f"A4:CF:12:9B:01:{index:02d}", host=f"192.168.50.{100 + index}", installed_at=station)
    with django_assert_max_num_queries(12):
        response = coord.get(f"{BASE}/devices")
    assert response.status_code == 200 and len(response.body) == 6


def test_metrics_and_target_overview_for_unconfigured_target(coord, layout):
    metrics = coord.get(f"{BASE}/metrics")
    assert {metric["key"] for metric in metrics.body} >= {"temperature_c", "humidity_percent", "power_w"}
    empty = coord.get(f"{BASE}/targets/room/{layout['other_room'].pk}")
    assert empty.status_code == 200
    assert (empty.body["installed_devices"], empty.body["channels"]) == ([], [])
    assert coord.get(f"{BASE}/targets/rack/1").status_code == 404


def test_bench_placed_in_a_station_slot_can_be_measured(coord, admin, layout):
    slot = StationSlot.objects.create(station=layout["station"], position_index=1, slot_code="A1")
    bench: Any = BenchFactory(setup_location=layout["station"], station_slot=slot)
    meter = _approved_profile(coord, admin)
    source = _source(coord, installed_at={"type": "station", "id": layout["station"].pk})
    response = coord.post(
        f"{BASE}/sources/{source.body['id']}/actions/bind-target",
        {"target_type": "bench", "target_id": bench.pk},
        format="json",
    )
    assert response.status_code == 200
    coord.post(
        f"{BASE}/sources/{source.body['id']}/channels",
        {"unit_id": 1, "profile_id": meter["id"], "target_type": "bench", "target_id": bench.pk},
        format="json",
    )
    overview = coord.get(f"{BASE}/targets/bench/{bench.pk}")
    assert len(overview.body["channels"]) == 1
