"""Gateway ingest into each channel's latest reading, and the room/station rollup dashboards read.

Design: docs/proposals/environment-telemetry.md §6.8, §7.1.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from core.labs.features.telemetry.exceptions import GatewayHasNoScope, GatewayNotRegistered
from core.labs.features.telemetry.public import IngestOperation, IngestReading, current_conditions, ingest_samples
from core.labs.models.telemetry import TelemetryDevice, TelemetryLatest

from .test_configuration_api import PROBE_MAP, _approved_profile, _asset, _client, _gateway, _source

pytestmark = pytest.mark.django_db
BASE = "/api/labs/telemetry"


@pytest.fixture
def setup():
    from core.labs.models import Room, Station

    coord = _client("ing-coord", "coord")
    admin = _client("ing-admin", "admin")
    room = Room.objects.create(sku="ING-R1", name="Ingest room")
    station = Station.objects.create(sku="ING-S1", name="Ingest station", room=room)
    meter = _approved_profile(coord, admin)
    probe = _approved_profile(coord, admin, key="es35_sw", read_map=PROBE_MAP)
    gateway = _gateway(coord, room)
    meter_source = _source(coord, installed_at={"type": "station", "id": station.pk}).body
    probe_source = _source(
        coord, uid="A4:CF:12:9B:00:35", host="192.168.50.22", installed_at={"type": "room", "id": room.pk}
    ).body
    power = coord.post(
        f"{BASE}/sources/{meter_source['id']}/channels",
        {"unit_id": 1, "profile_id": meter["id"], "target_type": "station", "target_id": station.pk},
        format="json",
    ).body["channels"][0]
    probe_channels = coord.post(
        f"{BASE}/sources/{probe_source['id']}/channels",
        {"unit_id": 1, "profile_id": probe["id"], "target_type": "room", "target_id": room.pk},
        format="json",
    ).body["channels"]
    by_metric = {channel["metric"]["id"]: channel["id"] for channel in probe_channels}
    gateway_device = TelemetryDevice.objects.get(pk=gateway["id"])
    return {
        "coord": coord,
        "room": room,
        "station": station,
        "gateway_equipment_id": int(gateway_device.device_uid.removeprefix("equipment-")),
        "meter_uid": meter_source["device_uid"],
        "probe_uid": probe_source["device_uid"],
        "power": power["id"],
        "temperature": by_metric["temperature_c"],
        "humidity": by_metric["humidity_percent"],
    }


def _op(uid, readings, *, at=None, sample=None):
    return IngestOperation(
        device_uid=uid,
        sample_id=sample or uuid.uuid4(),
        observed_at=at or timezone.now(),
        readings=tuple(readings),
    )


def test_readings_roll_up_to_station_and_room(setup):
    result = ingest_samples(
        gateway_equipment_id=setup["gateway_equipment_id"],
        operations=[
            _op(setup["meter_uid"], [IngestReading(setup["power"], Decimal("1830.5"))]),
            _op(
                setup["probe_uid"],
                [
                    IngestReading(setup["temperature"], Decimal("24.6")),
                    IngestReading(setup["humidity"], Decimal("45")),
                ],
            ),
        ],
    )
    assert [item.status for item in result.results] == ["accepted", "accepted"]
    conditions = current_conditions(room_ids=[setup["room"].pk], station_ids=[setup["station"].pk])
    station = conditions["stations"][setup["station"].pk]
    room = conditions["rooms"][setup["room"].pk]
    assert station.power_w == 1830.5 and station.temperature_c is None
    assert (room.temperature_c, room.humidity_percent, room.power_w) == (24.6, 45.0, 1830.5)
    assert room.channel_count == 3


def test_replays_older_and_failed_readings_never_overwrite_the_latest(setup):
    sample = uuid.uuid4()
    # Readings are attributed through the binding in force at observed_at, so stay after it started.
    now = timezone.now() + timedelta(seconds=30)
    operation = _op(setup["meter_uid"], [IngestReading(setup["power"], Decimal("100"))], at=now, sample=sample)
    gateway = setup["gateway_equipment_id"]
    assert ingest_samples(gateway_equipment_id=gateway, operations=[operation]).results[0].status == "accepted"
    assert ingest_samples(gateway_equipment_id=gateway, operations=[operation]).results[0].status == "duplicate"
    older = _op(setup["meter_uid"], [IngestReading(setup["power"], Decimal("5"))], at=now - timedelta(seconds=20))
    assert ingest_samples(gateway_equipment_id=gateway, operations=[older]).results[0].status == "accepted"
    latest = TelemetryLatest.objects.get(channel_id=setup["power"])
    assert latest.value == Decimal("100")

    silent = _op(
        setup["meter_uid"], [IngestReading(setup["power"], None, status="no_response")], at=now + timedelta(seconds=10)
    )
    ingest_samples(gateway_equipment_id=gateway, operations=[silent])
    latest.refresh_from_db()
    assert latest.status == "no_response" and latest.value is None
    # A channel that did not answer is no data, never 0.
    station = current_conditions(station_ids=[setup["station"].pk])["stations"]
    assert setup["station"].pk not in station


def test_bad_readings_are_rejected_one_by_one(setup):
    gateway = setup["gateway_equipment_id"]
    result = ingest_samples(
        gateway_equipment_id=gateway,
        operations=[
            _op(
                setup["probe_uid"],
                [
                    IngestReading(setup["humidity"], Decimal("120")),
                    IngestReading(setup["power"], Decimal("10")),  # belongs to another source
                    IngestReading(setup["temperature"], Decimal("21")),
                ],
            ),
            _op("FF:FF:FF:FF:FF:FF", [IngestReading(setup["temperature"], Decimal("21"))]),
            _op(
                setup["probe_uid"],
                [IngestReading(setup["temperature"], Decimal("21"))],
                at=timezone.now() + timedelta(hours=1),
            ),
        ],
    )
    first, unknown, future = result.results
    assert first.status == "partially_accepted"
    assert first.errors == [{"reading": 0, "code": "value_out_of_range"}, {"reading": 1, "code": "channel_not_bound"}]
    assert unknown.status == "rejected" and unknown.errors == [{"code": "source_not_claimed"}]
    assert future.errors == [{"code": "observed_at_out_of_range"}]


def test_readings_outside_the_gateway_scope_are_refused(setup):
    from core.labs.models import Room

    other_room = Room.objects.create(sku="ING-R2", name="Other room")
    other = _gateway(setup["coord"], other_room)
    other_equipment = int(TelemetryDevice.objects.get(pk=other["id"]).device_uid.removeprefix("equipment-"))
    result = ingest_samples(
        gateway_equipment_id=other_equipment,
        operations=[_op(setup["meter_uid"], [IngestReading(setup["power"], Decimal("50"))])],
    )
    assert result.results[0].errors == [{"reading": 0, "code": "outside_gateway_scope"}]
    assert not TelemetryLatest.objects.exists()


def test_unregistered_or_unscoped_gateways_are_refused(setup):
    with pytest.raises(GatewayNotRegistered):
        ingest_samples(gateway_equipment_id=_asset(), operations=[])
    unscoped = setup["coord"].post(f"{BASE}/gateways", {"equipment_id": _asset(), "kind": "room_host"}, format="json")
    equipment_id = int(TelemetryDevice.objects.get(pk=unscoped.body["id"]).device_uid.removeprefix("equipment-"))
    with pytest.raises(GatewayHasNoScope):
        ingest_samples(gateway_equipment_id=equipment_id, operations=[])


def test_stale_readings_are_not_current(setup):
    from core.labs.models.telemetry import ChannelTargetBinding

    ChannelTargetBinding.objects.filter(channel_id=setup["power"]).update(
        valid_from=timezone.now() - timedelta(hours=3)
    )
    gateway = setup["gateway_equipment_id"]
    old = _op(
        setup["meter_uid"], [IngestReading(setup["power"], Decimal("70"))], at=timezone.now() - timedelta(hours=2)
    )
    assert ingest_samples(gateway_equipment_id=gateway, operations=[old]).results[0].status == "accepted"
    assert current_conditions(station_ids=[setup["station"].pk])["stations"] == {}


def test_readings_from_before_the_binding_are_not_attributed(setup):
    early = _op(
        setup["meter_uid"], [IngestReading(setup["power"], Decimal("9"))], at=timezone.now() - timedelta(hours=1)
    )
    result = ingest_samples(gateway_equipment_id=setup["gateway_equipment_id"], operations=[early])
    assert result.results[0].errors == [{"reading": 0, "code": "channel_not_bound"}]
