"""Telemetry request and response payloads; serializers validate shape and never save models.

Wire rules (docs/api/response-standard.md): relations are `{id, name}` (targets add `type`, REL-13), enums are
`{value, label}`, date-times end in `_at`, booleans start with `is_`/`has_`, free-text search is `q`.
Requests name polymorphic targets with flat `<role>_type` / `<role>_id` pairs.
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api.summary_serializers import UserReferenceSerializer, embedded_resource
from core.common.api.wire_names import relation_name
from core.labs.features.base.serializers import (
    AppModelSerializer,
    ChoiceReferenceSerializer,
    NamedReferenceSerializer,
    to_choice_reference,
)
from core.labs.features.telemetry.contracts import TargetRef
from core.labs.models.telemetry import (
    GATEWAY_KINDS,
    SOURCE_KINDS,
    DeviceProfile,
    DeviceProfileStatus,
    DeviceProtocol,
    MetricAggregation,
    MetricCombination,
    MetricDefinition,
    MetricKind,
    ModbusFraming,
    SerialInterface,
    SerialParity,
    TelemetryChannel,
    TelemetryDevice,
    TelemetryDeviceKind,
    TelemetryDeviceRole,
    TelemetryDeviceState,
    TelemetryTargetType,
)

# ---- relations ---------------------------------------------------------------------------------


class TargetSerializer(serializers.Serializer):
    """REL-13 polymorphic relation to a room, station, bench or equipment item."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    type = serializers.ChoiceField(choices=TelemetryTargetType.choices)

    class Meta:
        ref_name = "TelemetryTarget"


def target_reference(target) -> dict | None:
    if target is None:
        return None
    resource = getattr(target, target.target_type, None)
    name = relation_name(resource) if resource is not None else f"Deleted {target.target_type}"
    return {"id": target.resource_id, "name": name, "type": target.target_type}


def named(instance, name: str) -> dict | None:
    return {"id": instance.pk, "name": name} if instance is not None else None


def equipment_reference(equipment) -> dict | None:
    return named(equipment, equipment.name or equipment.sku) if equipment is not None else None


def optional_target(data: dict, role: str) -> TargetRef | None:
    """Turn `<role>_type` / `<role>_id` into a `TargetRef`; both or neither."""
    target_type, target_id = data.pop(f"{role}_type", None), data.pop(f"{role}_id", None)
    if target_type is None and target_id is None:
        return None
    if target_type is None or target_id is None:
        raise serializers.ValidationError({f"{role}_type": "Give both the type and the id."})
    return TargetRef(type=target_type, id=target_id)


def required_target(data: dict, role: str) -> TargetRef:
    target = optional_target(data, role)
    if target is None:
        raise serializers.ValidationError({f"{role}_type": "This field is required."})
    return target


def _target_fields(role: str, *, required: bool, help_text: str) -> dict:
    return {
        f"{role}_type": serializers.ChoiceField(
            choices=TelemetryTargetType.choices, required=required, help_text=help_text
        ),
        f"{role}_id": serializers.IntegerField(min_value=1, required=required),
    }


# ---- metrics and profiles ----------------------------------------------------------------------


class MetricSerializer(AppModelSerializer):
    kind = serializers.SerializerMethodField()
    aggregation = serializers.SerializerMethodField()
    combine = serializers.SerializerMethodField()

    class Meta:
        model = MetricDefinition
        fields = ("key", "name", "unit", "value_min", "value_max", "kind", "aggregation", "combine", "decimals")
        read_only_fields = fields

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_kind(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.kind, MetricKind.choices)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_aggregation(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.aggregation, MetricAggregation.choices)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_combine(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.combine, MetricCombination.choices)


class DeviceProfileSerializer(AppModelSerializer):
    reference = serializers.CharField(read_only=True, help_text="`key@version`, recorded on every reading.")
    protocol = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    channel_count = serializers.IntegerField(read_only=True)
    created_by = UserReferenceSerializer(source="creator", read_only=True, allow_null=True)
    updated_by = UserReferenceSerializer(source="last_modified_by", read_only=True, allow_null=True)

    class Meta:
        model = DeviceProfile
        fields = (
            "id",
            "key",
            "version",
            "reference",
            "protocol",
            "manufacturer",
            "model",
            "status",
            "read_map",
            "comm_defaults",
            "notes",
            "approved_at",
            "channel_count",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_protocol(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.protocol, DeviceProtocol.choices)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_status(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.status, DeviceProfileStatus.choices)


class DeviceProfileCreateSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=64, help_text="Model code; an existing key gets a new version.")
    protocol = serializers.ChoiceField(choices=DeviceProtocol.choices)
    manufacturer = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    model = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    read_map = serializers.DictField(
        child=serializers.DictField(),
        allow_empty=False,
        help_text="Per metric key, how to read it (protocol-specific).",
    )
    comm_defaults = serializers.DictField(required=False, default=dict)
    notes = serializers.CharField(max_length=4000, required=False, allow_blank=True, default="")


class DeviceProfileListQuerySerializer(serializers.Serializer):
    key = serializers.CharField(required=False)
    status = serializers.ChoiceField(choices=DeviceProfileStatus.choices, required=False)
    protocol = serializers.ChoiceField(choices=DeviceProtocol.choices, required=False)
    q = serializers.CharField(required=False, help_text="Free-text search in key, manufacturer and model.")


# ---- channels ----------------------------------------------------------------------------------


class MeasuresSerializer(serializers.Serializer):
    target = TargetSerializer()
    started_at = serializers.DateTimeField()

    class Meta:
        ref_name = "TelemetryChannelMeasures"


class ChannelSerializer(AppModelSerializer):
    metric = serializers.SerializerMethodField()
    unit = serializers.CharField(source="metric.unit", read_only=True)
    unit_id = serializers.SerializerMethodField()
    profile = serializers.SerializerMethodField()
    measures = serializers.SerializerMethodField()
    field_device = serializers.SerializerMethodField()

    class Meta:
        model = TelemetryChannel
        fields = (
            "id",
            "label",
            "source",
            "metric",
            "unit",
            "is_enabled",
            "unit_id",
            "profile",
            "measures",
            "field_device",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_fields(self):
        fields = super().get_fields()
        fields["source"] = serializers.SerializerMethodField()  # declared here: `source` is a Field attribute
        return fields

    @extend_schema_field(NamedReferenceSerializer)
    def get_source(self, obj) -> dict | None:
        return named(obj.source, obj.source.model or obj.source.device_uid)

    @extend_schema_field(serializers.DictField(help_text="Relation `{id, name}`; `id` is the metric key."))
    def get_metric(self, obj) -> dict:
        return {"id": obj.metric.key, "name": obj.metric.name}

    @extend_schema_field(serializers.IntegerField(allow_null=True, help_text="Modbus unit ID (bus address)."))
    def get_unit_id(self, obj) -> int | None:
        settings = getattr(obj, "modbus_settings", None)
        return settings.unit_id if settings is not None else None

    @extend_schema_field(NamedReferenceSerializer(allow_null=True))
    def get_profile(self, obj) -> dict | None:
        settings = getattr(obj, "modbus_settings", None)
        return named(settings.profile, settings.profile.reference) if settings is not None else None

    @extend_schema_field(MeasuresSerializer(allow_null=True))
    def get_measures(self, obj) -> dict | None:
        bindings = getattr(obj, "open_bindings", None)
        if not bindings:
            return None
        return {"target": target_reference(bindings[0].target), "started_at": bindings[0].valid_from}

    @extend_schema_field(NamedReferenceSerializer(allow_null=True))
    def get_field_device(self, obj) -> dict | None:
        return equipment_reference(obj.field_device_equipment)


@embedded_resource
class EmbeddedChannelSerializer(ChannelSerializer):
    class Meta(ChannelSerializer.Meta):
        ref_name = "TelemetryEmbeddedChannel"


class ChannelsFromProfileSerializer(serializers.Serializer):
    unit_id = serializers.IntegerField(min_value=1, max_value=247, help_text="Modbus unit ID (bus address).")
    profile_id = serializers.IntegerField(min_value=1)
    metrics = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=False, help_text="Default: all profile metrics."
    )
    field_device_equipment_id = serializers.IntegerField(required=False, allow_null=True, default=None)

    def get_fields(self):
        fields = super().get_fields()
        fields["label"] = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
        fields.update(_target_fields("target", required=False, help_text="What the new channels measure."))
        return fields


class ChannelUpdateSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField(required=False)
    field_device_equipment_id = serializers.IntegerField(required=False, allow_null=True)

    def get_fields(self):
        fields = super().get_fields()
        fields["label"] = serializers.CharField(max_length=120, required=False, allow_blank=True)
        return fields


class BindTargetSerializer(serializers.Serializer):
    def get_fields(self):
        return _target_fields("target", required=True, help_text="Room, station, bench or equipment.")


# ---- devices -----------------------------------------------------------------------------------


class ModbusSettingsInputSerializer(serializers.Serializer):
    network_host = serializers.CharField(max_length=253, help_text="IP address or host name.")
    port = serializers.IntegerField(min_value=1, max_value=65535, required=False, default=502)
    framing = serializers.ChoiceField(choices=ModbusFraming.choices, required=False, default=ModbusFraming.MBAP)
    serial_interface = serializers.ChoiceField(
        choices=SerialInterface.choices, required=False, allow_blank=True, default=SerialInterface.NONE
    )
    baud_rate = serializers.IntegerField(required=False, allow_null=True, default=None)
    parity = serializers.ChoiceField(choices=SerialParity.choices, required=False, allow_blank=True, default="")
    data_bits = serializers.IntegerField(required=False, allow_null=True, default=None)
    stop_bits = serializers.IntegerField(required=False, allow_null=True, default=None)
    request_timeout_ms = serializers.IntegerField(required=False, default=800)
    has_shared_bus = serializers.BooleanField(
        required=False, default=True, help_text="A half-duplex bus is behind the device: one request at a time."
    )

    class Meta:
        ref_name = "TelemetryModbusSettingsInput"

    def to_internal_value(self, data):
        values = super().to_internal_value(data)
        values["serialize_requests"] = values.pop("has_shared_bus")
        return values


class ModbusSettingsSerializer(serializers.Serializer):
    network_host = serializers.CharField()
    port = serializers.IntegerField()
    framing = serializers.SerializerMethodField()
    serial_interface = serializers.SerializerMethodField()
    baud_rate = serializers.IntegerField(allow_null=True)
    parity = serializers.SerializerMethodField()
    data_bits = serializers.IntegerField(allow_null=True)
    stop_bits = serializers.IntegerField(allow_null=True)
    request_timeout_ms = serializers.IntegerField()
    has_shared_bus = serializers.BooleanField(source="serialize_requests")

    class Meta:
        ref_name = "TelemetryModbusSettings"

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_framing(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.framing, ModbusFraming.choices)

    @extend_schema_field(ChoiceReferenceSerializer(allow_null=True))
    def get_serial_interface(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.serial_interface or None, SerialInterface.choices)

    @extend_schema_field(ChoiceReferenceSerializer(allow_null=True))
    def get_parity(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.parity or None, SerialParity.choices)


class DeviceSerializer(AppModelSerializer):
    role = serializers.SerializerMethodField()
    kind = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()
    equipment = serializers.SerializerMethodField()
    install_location = serializers.SerializerMethodField()
    room = serializers.SerializerMethodField()
    scope = serializers.SerializerMethodField()
    modbus = serializers.SerializerMethodField()
    channel_count = serializers.IntegerField(read_only=True)
    reported_by = serializers.SerializerMethodField()

    class Meta:
        model = TelemetryDevice
        fields: tuple[str, ...] = (
            "id",
            "role",
            "kind",
            "device_uid",
            "state",
            "manufacturer",
            "model",
            "equipment",
            "install_location",
            "room",
            "scope",
            "modbus",
            "channel_count",
            "config_version",
            "config_version_applied",
            "reported_by",
            "last_seen_address",
            "first_seen_at",
            "last_seen_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_role(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.role, TelemetryDeviceRole.choices)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_kind(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.kind, TelemetryDeviceKind.choices)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_state(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.state, TelemetryDeviceState.choices)

    @extend_schema_field(NamedReferenceSerializer(allow_null=True))
    def get_equipment(self, obj) -> dict | None:
        return equipment_reference(obj.equipment)

    @extend_schema_field(TargetSerializer(allow_null=True))
    def get_install_location(self, obj) -> dict | None:
        return target_reference(obj.installed_at)

    @extend_schema_field(NamedReferenceSerializer(allow_null=True))
    def get_room(self, obj) -> dict | None:
        room_id = getattr(obj, "installed_room_id", None)
        if room_id is not None:
            return {"id": room_id, "name": obj.installed_room_name}
        scopes = getattr(obj, "open_scopes", None) or []
        if scopes and scopes[0].target.room_id:
            return {"id": scopes[0].target.room_id, "name": scopes[0].target.room.name}
        return None

    @extend_schema_field(TargetSerializer(allow_null=True))
    def get_scope(self, obj) -> dict | None:
        scopes = getattr(obj, "open_scopes", None) or []
        return target_reference(scopes[0].target) if scopes else None

    @extend_schema_field(ModbusSettingsSerializer(allow_null=True))
    def get_modbus(self, obj) -> dict | None:
        settings = getattr(obj, "modbus_settings", None)
        return ModbusSettingsSerializer(settings).data if settings is not None else None

    @extend_schema_field(NamedReferenceSerializer(allow_null=True))
    def get_reported_by(self, obj) -> dict | None:
        return named(obj.reported_by, obj.reported_by.device_uid) if obj.reported_by else None


@embedded_resource
class EmbeddedDeviceSerializer(DeviceSerializer):
    class Meta(DeviceSerializer.Meta):
        ref_name = "TelemetryEmbeddedDevice"


class DeviceDetailSerializer(DeviceSerializer):
    channels = EmbeddedChannelSerializer(source="channel_list", many=True, read_only=True)

    class Meta(DeviceSerializer.Meta):
        fields = (*DeviceSerializer.Meta.fields, "channels")
        read_only_fields = fields


class DeviceListQuerySerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=TelemetryDeviceRole.choices, required=False)
    kind = serializers.ChoiceField(choices=TelemetryDeviceKind.choices, required=False)
    state = serializers.ChoiceField(choices=TelemetryDeviceState.choices, required=False)
    room_id = serializers.IntegerField(required=False, min_value=1, help_text="Installed in, or covering, this room.")
    q = serializers.CharField(required=False, help_text="Free-text search: UID, model, asset, IP address.")


class GatewayCreateSerializer(serializers.Serializer):
    equipment_id = serializers.IntegerField(min_value=1, help_text="The gateway PC's inventory asset.")
    kind = serializers.ChoiceField(choices=[(kind.value, kind.label) for kind in GATEWAY_KINDS])


class _SourceWriteSerializer(serializers.Serializer):
    modbus = ModbusSettingsInputSerializer(required=False, allow_null=True, default=None)
    manufacturer = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    model = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")

    def get_fields(self):
        fields = super().get_fields()
        fields.update(_target_fields("install_location", required=True, help_text="Where the device physically is."))
        return fields


class SourceCreateSerializer(_SourceWriteSerializer):
    kind = serializers.ChoiceField(choices=[(kind.value, kind.label) for kind in SOURCE_KINDS])
    device_uid = serializers.CharField(max_length=64, help_text="MAC address or serial number from the label.")
    equipment_id = serializers.IntegerField(min_value=1, help_text="The device's inventory asset.")


class SourceClaimSerializer(_SourceWriteSerializer):
    equipment_id = serializers.IntegerField(min_value=1, help_text="The device's inventory asset.")


class SourceUpdateSerializer(serializers.Serializer):
    modbus = ModbusSettingsInputSerializer(required=False)
    manufacturer = serializers.CharField(max_length=120, required=False, allow_blank=True)
    model = serializers.CharField(max_length=120, required=False, allow_blank=True)

    def get_fields(self):
        fields = super().get_fields()
        fields.update(_target_fields("install_location", required=False, help_text="Move the device."))
        return fields


class ScopeBindingSerializer(serializers.Serializer):
    gateway_id = serializers.IntegerField()
    target = TargetSerializer()
    started_at = serializers.DateTimeField()

    class Meta:
        ref_name = "TelemetryScopeBinding"


# ---- target overview ---------------------------------------------------------------------------


class TargetOverviewSerializer(serializers.Serializer):
    target = TargetSerializer()
    installed_devices = EmbeddedDeviceSerializer(many=True, help_text="Devices installed at this target.")
    channels = EmbeddedChannelSerializer(many=True, help_text="Measurements currently about this target.")

    class Meta:
        ref_name = "TelemetryTargetOverview"
