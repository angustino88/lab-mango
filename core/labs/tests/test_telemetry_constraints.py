"""PostgreSQL guards for telemetry configuration (migrations 0002-0003).

Every write here bypasses `clean()`: the database itself must reject the invalid row.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.models import Room, Station
from core.labs.models.telemetry import (
    ChannelTargetBinding,
    DeviceProfile,
    DeviceProfileStatus,
    DeviceProtocol,
    GatewayScopeBinding,
    MetricDefinition,
    ModbusChannelSettings,
    ModbusSourceSettings,
    TelemetryChannel,
    TelemetryDevice,
    TelemetryDeviceKind,
    TelemetryDeviceRole,
    TelemetryDeviceState,
    TelemetryTarget,
    TelemetryTargetType,
    validate_modbus_read_map,
)
from tests.factories import ComputingEquipmentFactory

pytestmark = pytest.mark.django_db

VALID_READ_MAP = {"power_w": {"function_code": 3, "register": 0, "words": 2, "type": "float32", "scale": 1}}


def _rejects(constraint: str, create, *args, **values):
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        create(*args, **values)


@pytest.fixture
def room():
    return Room.objects.create(sku="TEL-R-1", name="Telemetry room")


@pytest.fixture
def room_target(room):
    return TelemetryTarget.objects.create(target_type=TelemetryTargetType.ROOM, room=room)


@pytest.fixture
def gateway():
    return TelemetryDevice.objects.create(
        role=TelemetryDeviceRole.GATEWAY,
        kind=TelemetryDeviceKind.ROOM_HOST,
        device_uid="gateway-agent-uid-1",
        state=TelemetryDeviceState.CLAIMED,
        equipment=ComputingEquipmentFactory(),
    )


@pytest.fixture
def source(room_target):
    return TelemetryDevice.objects.create(
        role=TelemetryDeviceRole.SOURCE,
        kind=TelemetryDeviceKind.MODBUS_TCP,
        device_uid="A4:CF:12:9B:00:21",
        state=TelemetryDeviceState.CLAIMED,
        equipment=ComputingEquipmentFactory(),
        installed_at=room_target,
    )


@pytest.fixture
def profile():
    return DeviceProfile.objects.create(key="meter_x", protocol=DeviceProtocol.MODBUS, read_map=VALID_READ_MAP)


@pytest.fixture
def channel(source):
    return TelemetryChannel.objects.create(source=source, metric_id="power_w")


# --- targets ------------------------------------------------------------------------------------


def test_target_rejects_no_resource():
    _rejects("telemetry_target_type_matches_resource", TelemetryTarget.objects.create, target_type="room")


def test_target_rejects_two_resources(room):
    station = Station.objects.create(sku="TEL-S-1", name="Station", room=room)
    _rejects(
        "telemetry_target_type_matches_resource",
        TelemetryTarget.objects.create,
        target_type="room",
        room=room,
        station=station,
    )


def test_target_rejects_type_naming_another_resource(room):
    _rejects(
        "telemetry_target_type_matches_resource", TelemetryTarget.objects.create, target_type="station", room=room
    )


def test_target_is_unique_per_resource(room_target, room):
    _rejects("telemetry_target_room_uniq", TelemetryTarget.objects.create, target_type="room", room=room)


# --- metrics ------------------------------------------------------------------------------------


def test_v1_metrics_are_seeded_with_physical_ranges():
    metrics = {metric.key: metric for metric in MetricDefinition.objects.all()}
    assert set(metrics) >= {"temperature_c", "humidity_percent", "power_w"}
    assert metrics["temperature_c"].value_min == Decimal("-273.15")
    assert (metrics["humidity_percent"].value_min, metrics["humidity_percent"].value_max) == (0, 100)
    assert metrics["humidity_percent"].accepts(Decimal("100")) and not metrics["humidity_percent"].accepts(
        Decimal("100.1")
    )
    assert not metrics["power_w"].accepts(Decimal("-1"))


def test_metric_range_must_be_ordered():
    _rejects(
        "telemetry_metric_range_ordered",
        MetricDefinition.objects.create,
        key="bad_range",
        name="Bad",
        unit="x",
        value_min=Decimal("5"),
        value_max=Decimal("1"),
    )


def test_counter_metric_must_roll_up_as_delta():
    _rejects(
        "telemetry_metric_counter_uses_delta",
        MetricDefinition.objects.create,
        key="energy_wh_bad",
        name="Energy",
        unit="Wh",
        kind="counter",
        aggregation="mean",
    )


# --- device profiles ----------------------------------------------------------------------------


def test_profile_key_and_version_are_unique(profile):
    _rejects(
        "telemetry_profile_key_version_uniq",
        DeviceProfile.objects.create,
        key="meter_x",
        version=1,
        protocol=DeviceProtocol.MODBUS,
        read_map=VALID_READ_MAP,
    )


def test_approved_profile_needs_approval_time():
    _rejects(
        "telemetry_profile_approved_has_time",
        DeviceProfile.objects.create,
        key="meter_y",
        protocol=DeviceProtocol.MODBUS,
        read_map=VALID_READ_MAP,
        status=DeviceProfileStatus.APPROVED,
    )


def test_profile_clean_rejects_invalid_modbus_read_map():
    profile = DeviceProfile(
        key="meter_z",
        protocol=DeviceProtocol.MODBUS,
        read_map={"power_w": {"function_code": 6, "register": 70000, "type": "float64"}},
    )
    with pytest.raises(ValidationError) as error:
        profile.clean()
    assert set(error.value.message_dict) == {
        "read_map.power_w.function_code",
        "read_map.power_w.register",
        "read_map.power_w.type",
    }


@pytest.mark.parametrize(
    ("entry", "field"),
    [
        ({"function_code": 3, "register": 0, "type": "float32", "words": 1}, "read_map.m.words"),
        ({"function_code": 3, "register": 0, "type": "int16", "word_order": "middle"}, "read_map.m.word_order"),
        ({"function_code": 4, "register": 0, "type": "int16", "scale": 0}, "read_map.m.scale"),
        ({"function_code": 4, "register": True, "type": "int16"}, "read_map.m.register"),
    ],
)
def test_modbus_read_map_validation_names_the_bad_field(entry, field):
    assert field in validate_modbus_read_map({"m": entry})


def test_modbus_read_map_accepts_valid_entries():
    assert validate_modbus_read_map(VALID_READ_MAP) == {}
    assert validate_modbus_read_map({}) == {"read_map": "Must be a non-empty object keyed by metric."}


# --- devices ------------------------------------------------------------------------------------


def test_device_kind_must_match_role():
    _rejects(
        "telemetry_device_kind_matches_role",
        TelemetryDevice.objects.create,
        role=TelemetryDeviceRole.SOURCE,
        kind=TelemetryDeviceKind.ROOM_HOST,
        device_uid="x-1",
    )


def test_device_uid_is_required():
    _rejects(
        "telemetry_device_uid_present",
        TelemetryDevice.objects.create,
        role=TelemetryDeviceRole.SOURCE,
        kind=TelemetryDeviceKind.MODBUS_TCP,
        device_uid="",
    )


def test_device_uid_is_unique(source, room_target):
    _rejects(
        "device_uid",
        TelemetryDevice.objects.create,
        role=TelemetryDeviceRole.SOURCE,
        kind=TelemetryDeviceKind.MODBUS_TCP,
        device_uid=source.device_uid,
    )


def test_discovered_source_needs_no_equipment_or_location():
    device = TelemetryDevice.objects.create(
        role=TelemetryDeviceRole.SOURCE, kind=TelemetryDeviceKind.MODBUS_TCP, device_uid="discovered-1"
    )
    assert device.state == TelemetryDeviceState.DISCOVERED


def test_claimed_device_needs_equipment(room_target):
    _rejects(
        "telemetry_device_claimed_has_equipment",
        TelemetryDevice.objects.create,
        role=TelemetryDeviceRole.SOURCE,
        kind=TelemetryDeviceKind.MODBUS_TCP,
        device_uid="claimed-1",
        state=TelemetryDeviceState.CLAIMED,
        installed_at=room_target,
    )


def test_claimed_source_needs_install_location():
    _rejects(
        "telemetry_source_claimed_installed",
        TelemetryDevice.objects.create,
        role=TelemetryDeviceRole.SOURCE,
        kind=TelemetryDeviceKind.MODBUS_TCP,
        device_uid="claimed-2",
        state=TelemetryDeviceState.CLAIMED,
        equipment=ComputingEquipmentFactory(),
    )


def test_gateway_has_no_install_location(room_target):
    _rejects(
        "telemetry_gateway_not_installed",
        TelemetryDevice.objects.create,
        role=TelemetryDeviceRole.GATEWAY,
        kind=TelemetryDeviceKind.ROOM_HOST,
        device_uid="gw-2",
        installed_at=room_target,
    )


def test_applied_config_version_cannot_exceed_issued(gateway):
    with pytest.raises(IntegrityError, match="telemetry_device_applied_version_known"), transaction.atomic():
        TelemetryDevice.objects.filter(pk=gateway.pk).update(config_version=3, config_version_applied=4)


# --- Modbus settings ----------------------------------------------------------------------------


def _modbus(source, **values):
    defaults = {"device": source, "network_host": "192.168.50.21"}
    return ModbusSourceSettings.objects.create(**{**defaults, **values})


def test_modbus_address_is_unique(source, room_target):
    _modbus(source)
    other = TelemetryDevice.objects.create(
        role=TelemetryDeviceRole.SOURCE,
        kind=TelemetryDeviceKind.MODBUS_TCP,
        device_uid="A4:CF:12:9B:00:35",
        state=TelemetryDeviceState.CLAIMED,
        equipment=ComputingEquipmentFactory(),
        installed_at=room_target,
    )
    _rejects("telemetry_modbus_address_uniq", _modbus, other)


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"port": 0}, "telemetry_modbus_port_range"),
        ({"port": 70000}, "telemetry_modbus_port_range"),
        ({"network_host": ""}, "telemetry_modbus_host_present"),
        ({"request_timeout_ms": 10}, "telemetry_modbus_timeout_range"),
        ({"serial_interface": "rs485"}, "telemetry_modbus_serial_all_or_none"),
        ({"baud_rate": 9600}, "telemetry_modbus_serial_all_or_none"),
        (
            {"serial_interface": "rs485", "baud_rate": 9600, "parity": "N", "data_bits": 9, "stop_bits": 1},
            "telemetry_modbus_serial_all_or_none",
        ),
    ],
)
def test_modbus_settings_reject_invalid_values(source, values, constraint):
    _rejects(constraint, _modbus, source, **values)


def test_modbus_settings_accept_converter_and_native_device(source):
    settings = _modbus(source, serial_interface="rs485", baud_rate=9600, parity="N", data_bits=8, stop_bits=1)
    assert str(settings) == "192.168.50.21:502"


# --- channels -----------------------------------------------------------------------------------


def test_modbus_channel_unit_and_metric_unique_per_source(source, channel, profile):
    ModbusChannelSettings.objects.create(
        channel=channel, source=source, metric_id="power_w", unit_id=1, profile=profile
    )
    other = TelemetryChannel.objects.create(source=source, metric_id="power_w")
    _rejects(
        "telemetry_modbus_channel_uniq",
        ModbusChannelSettings.objects.create,
        channel=other,
        source=source,
        metric_id="power_w",
        unit_id=1,
        profile=profile,
    )


@pytest.mark.parametrize("unit_id", [0, 248])
def test_modbus_channel_unit_id_in_range(source, channel, profile, unit_id):
    _rejects(
        "telemetry_modbus_unit_range",
        ModbusChannelSettings.objects.create,
        channel=channel,
        source=source,
        metric_id="power_w",
        unit_id=unit_id,
        profile=profile,
    )


# --- bindings -----------------------------------------------------------------------------------


def test_channel_measures_one_target_at_a_time(channel, room_target, room):
    now = timezone.now()
    station_target = TelemetryTarget.objects.create(
        target_type=TelemetryTargetType.STATION,
        station=Station.objects.create(sku="TEL-S-2", name="Station", room=room),
    )
    ChannelTargetBinding.objects.create(channel=channel, target=room_target, valid_from=now)
    _rejects(
        "telemetry_channel_one_target",
        ChannelTargetBinding.objects.create,
        channel=channel,
        target=station_target,
        valid_from=now + timedelta(hours=1),
    )


def test_channel_rebinding_after_close_is_allowed(channel, room_target):
    now = timezone.now()
    ChannelTargetBinding.objects.create(
        channel=channel, target=room_target, valid_from=now, valid_to=now + timedelta(hours=1)
    )
    later = ChannelTargetBinding.objects.create(
        channel=channel, target=room_target, valid_from=now + timedelta(hours=1)
    )
    assert later.pk is not None


def test_binding_range_must_be_positive(channel, room_target):
    now = timezone.now()
    _rejects(
        "telemetry_channel_bind_valid_range",
        ChannelTargetBinding.objects.create,
        channel=channel,
        target=room_target,
        valid_from=now,
        valid_to=now,
    )


def _scope(gateway, target, start, kind=TelemetryDeviceKind.ROOM_HOST):
    return GatewayScopeBinding.objects.create(gateway=gateway, gateway_kind=kind, target=target, valid_from=start)


def test_gateway_has_one_scope_at_a_time(gateway, room_target):
    now = timezone.now()
    _scope(gateway, room_target, now)
    other_room = TelemetryTarget.objects.create(
        target_type=TelemetryTargetType.ROOM, room=Room.objects.create(sku="TEL-R-2", name="Other")
    )
    _rejects("telemetry_scope_one_per_gateway", _scope, gateway, other_room, now + timedelta(minutes=5))


def test_room_has_one_room_gateway_at_a_time(gateway, room_target):
    now = timezone.now()
    _scope(gateway, room_target, now)
    second = TelemetryDevice.objects.create(
        role=TelemetryDeviceRole.GATEWAY,
        kind=TelemetryDeviceKind.ROOM_HOST,
        device_uid="gateway-agent-uid-2",
        state=TelemetryDeviceState.CLAIMED,
        equipment=ComputingEquipmentFactory(),
    )
    _rejects("telemetry_scope_one_room_host", _scope, second, room_target, now + timedelta(minutes=5))


def test_scope_gateway_kind_must_be_a_gateway_kind(gateway, room_target):
    _rejects(
        "telemetry_scope_gateway_kind_valid",
        _scope,
        gateway,
        room_target,
        timezone.now(),
        kind=TelemetryDeviceKind.MODBUS_TCP,
    )
