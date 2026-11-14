"""Explicit station read projections and write requests; serializers never save models."""

import math

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api.options import OptionsQueryMixin
from core.common.api.summary_serializers import StatusSummarySerializer, UserReferenceSerializer, embedded_resource
from core.labs.features.base.resource_images import ResourceImageURLField
from core.labs.features.base.serializers import (
    AppModelSerializer,
    ChoiceReferenceSerializer,
    Coordinate3DSerializer,
    NamedReferenceSerializer,
    ResourceWriteSerializerMixin,
    UIDNamedReferenceSerializer,
    to_choice_reference,
)
from core.labs.features.locations.api.serializers import LocationLifecycleWriteSerializer, LocationStateFieldsMixin
from core.labs.models.resource.base.status import ResourceLifecycleStatus
from core.labs.models.resource.location.station import Station, StationStatus, StationStatusRecord, StationType
from core.labs.models.resource.location.station_slot import StationSlot, StationSlotStatus

from .filters import STATION_FILTERS


class StationStatusSummarySerializer(StatusSummarySerializer):
    """The deprecated seven-value status, computed from lifecycle, condition, access and activity."""


class StationLifecycleWriteSerializer(LocationLifecycleWriteSerializer):
    pass


# Deprecated slot inputs (RS3): the old status values and ``is_active`` map onto ``service_status``.
LEGACY_SLOT_STATUS = {
    "available": StationSlotStatus.IN_SERVICE,
    "occupied": StationSlotStatus.IN_SERVICE,
    "reserved": StationSlotStatus.IN_SERVICE,
    "maintenance": StationSlotStatus.OUT_OF_SERVICE,
    "out_of_service": StationSlotStatus.OUT_OF_SERVICE,
    "in_service": StationSlotStatus.IN_SERVICE,
    "retired": StationSlotStatus.RETIRED,
}


class StationPlacementSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    room_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    slot_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    power_reserved_w = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False)
    position = serializers.JSONField(required=False, allow_null=True)
    orientation_degrees = serializers.IntegerField(min_value=0, max_value=359, required=False)

    def validate_position(self, value):
        if value is None:
            return value
        if isinstance(value, dict):
            if set(value) != {"x", "y", "z"}:
                raise serializers.ValidationError("Position must contain exactly x, y, and z.")
            raw_coordinates = [value[axis] for axis in ("x", "y", "z")]
        elif isinstance(value, list):
            if len(value) != 3:
                raise serializers.ValidationError("Position list must contain exactly 3 coordinates [x, y, z].")
            raw_coordinates = value
        else:
            raise serializers.ValidationError("Position must be a coordinate object or 3-element list.")

        coordinates = []
        for coordinate in raw_coordinates:
            if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
                raise serializers.ValidationError("Coordinates must be JSON numbers.")
            numeric_coordinate = float(coordinate)
            if not math.isfinite(numeric_coordinate) or abs(numeric_coordinate) > 1_000_000:
                raise serializers.ValidationError("Coordinates must be finite and within the supported range.")
            coordinates.append(numeric_coordinate)
        return coordinates

    def validate(self, attrs):
        if "room_id" in attrs and attrs["room_id"] is None and attrs.get("slot_id") is not None:
            raise serializers.ValidationError({"slot_id": "A slot requires a room."})
        if not attrs:
            raise serializers.ValidationError("Provide at least one placement field.")
        return attrs


class StationCreateSerializer(ResourceWriteSerializerMixin, serializers.ModelSerializer):
    department_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    group_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    owner_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    type_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    room_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    slot_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    position = serializers.JSONField(required=False, allow_null=True)
    orientation_degrees = serializers.IntegerField(min_value=0, max_value=359, required=False)
    utilities = serializers.DictField(required=False)

    validate_position = StationPlacementSerializer.validate_position

    class Meta:
        model = Station
        fields = (
            "sku",
            "name",
            "department_id",
            "group_id",
            "owner_id",
            "remark",
            "label",
            "type_id",
            "room_id",
            "slot_id",
            "position",
            "height_mm",
            "width_mm",
            "depth_mm",
            "orientation_degrees",
            "max_load_kg",
            "bench_capacity",
            "max_concurrent_users",
            "usable_surface_mm2",
            "power_capacity_w",
            "power_reserved_w",
            "cooling_capacity_w",
            "network_port_capacity",
            "utilities",
            "safety_classification",
        )
        validators = []
        extra_kwargs = {"sku": {"validators": []}}

    def validate(self, attrs):
        capacity = attrs.get("power_capacity_w")
        reserved = attrs.get("power_reserved_w", 0)
        if capacity is not None and reserved > capacity:
            raise serializers.ValidationError({"power_reserved_w": "Reserved power exceeds station capacity."})
        if "room_id" in attrs and attrs["room_id"] is None and attrs.get("slot_id") is not None:
            raise serializers.ValidationError({"slot_id": "A slot requires a room."})
        return attrs


class StationUpdateSerializer(StationCreateSerializer):
    class Meta(StationCreateSerializer.Meta):
        extra_kwargs = {}


class StationSlotCreateSerializer(ResourceWriteSerializerMixin, serializers.ModelSerializer):
    compatible_bench_types = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False)
    utilities = serializers.DictField(required=False)
    service_status = serializers.ChoiceField(choices=StationSlotStatus.choices, required=False)
    status = serializers.ChoiceField(
        choices=sorted(LEGACY_SLOT_STATUS), required=False, help_text="Deprecated: use service_status."
    )
    is_active = serializers.BooleanField(required=False, help_text="Deprecated: use service_status.")

    class Meta:
        model = StationSlot
        fields = (
            "position_index",
            "slot_code",
            "label",
            "is_active",
            "status",
            "service_status",
            "width_mm",
            "depth_mm",
            "height_mm",
            "max_load_kg",
            "power_capacity_w",
            "network_port_count",
            "utilities",
            "compatible_bench_types",
        )
        validators = []

    def validate(self, attrs):
        """Map the deprecated inputs; ``service_status`` wins, then ``status``, then ``is_active``."""
        attrs = super().validate(attrs)
        legacy_status = attrs.pop("status", None)
        is_active = attrs.pop("is_active", None)
        if "service_status" not in attrs:
            if legacy_status is not None:
                attrs["service_status"] = LEGACY_SLOT_STATUS[legacy_status]
            elif is_active is not None:
                attrs["service_status"] = (
                    StationSlotStatus.IN_SERVICE if is_active else StationSlotStatus.OUT_OF_SERVICE
                )
        if "service_status" in attrs:
            attrs["status"] = attrs.pop("service_status")
        return attrs


class StationSlotUpdateSerializer(StationSlotCreateSerializer):
    class Meta(StationSlotCreateSerializer.Meta):
        extra_kwargs = {"position_index": {"required": False}, "slot_code": {"required": False}}


class StationTypeWriteSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    name = serializers.CharField(max_length=255)


class StationStatusWriteSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    """Deprecated: mapped onto lifecycle, access policy and downtime. ``reserved`` cannot be set."""

    status = serializers.ChoiceField(choices=StationStatus.choices)
    metadata = serializers.DictField(required=False, default=dict)


StationListQuerySerializer = STATION_FILTERS.serializer("StationListQuerySerializer")


class StationSlotSerializer(AppModelSerializer):
    status = serializers.SerializerMethodField(
        read_only=True, help_text="Deprecated: available, occupied, out_of_service or retired (occupied is computed)."
    )
    service_status = serializers.SerializerMethodField()
    station = NamedReferenceSerializer(read_only=True)
    is_occupied = serializers.BooleanField(source="occupied", read_only=True, default=False)
    is_active = serializers.SerializerMethodField(help_text="Deprecated: service_status is in_service.")

    class Meta:
        model = StationSlot
        fields = (
            "id",
            "station",
            *StationSlotCreateSerializer.Meta.fields,
            "is_occupied",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_status(self, obj) -> dict[str, str] | None:
        if obj.status == StationSlotStatus.IN_SERVICE:
            return to_choice_reference("occupied" if getattr(obj, "occupied", False) else "available")
        return to_choice_reference(obj.status)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_service_status(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.status, StationSlotStatus.choices)

    def get_is_active(self, obj) -> bool:
        return obj.status == StationSlotStatus.IN_SERVICE


class StationSerializer(LocationStateFieldsMixin, AppModelSerializer):
    location_resource_type = "station"

    image_url = ResourceImageURLField()
    group = NamedReferenceSerializer(read_only=True, allow_null=True)
    department = NamedReferenceSerializer(read_only=True, allow_null=True)
    owner = NamedReferenceSerializer(read_only=True, allow_null=True)
    type = NamedReferenceSerializer(read_only=True, allow_null=True)
    room = UIDNamedReferenceSerializer(read_only=True, allow_null=True)
    slot = NamedReferenceSerializer(read_only=True, allow_null=True)
    position = serializers.SerializerMethodField(read_only=True)
    active_bench_count = serializers.IntegerField(read_only=True)
    allocated_power_w = serializers.IntegerField(read_only=True)
    available_slot_count = serializers.IntegerField(read_only=True)
    # Annotated by stations selectors; reading bench_slots.count() here issued one COUNT per row.
    slot_count = serializers.IntegerField(read_only=True)
    slots_url = serializers.SerializerMethodField()
    location_path = serializers.CharField(source="get_location_path", read_only=True)
    available_power_w = serializers.SerializerMethodField()

    class Meta:
        model = Station
        fields = (
            "id",
            "uid",
            "sku",
            "name",
            "department",
            "group",
            "owner",
            "remark",
            "label",
            "type",
            "room",
            "slot",
            "position",
            "height_mm",
            "width_mm",
            "depth_mm",
            "orientation_degrees",
            "max_load_kg",
            "bench_capacity",
            "max_concurrent_users",
            "usable_surface_mm2",
            "power_capacity_w",
            "power_reserved_w",
            "cooling_capacity_w",
            "network_port_capacity",
            "utilities",
            *LocationStateFieldsMixin.STATE_FIELDS,
            "safety_classification",
            "image_url",
            "active_bench_count",
            "allocated_power_w",
            "available_power_w",
            "available_slot_count",
            "location_path",
            "slot_count",
            "slots_url",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(Coordinate3DSerializer(allow_null=True))
    def get_position(self, obj) -> dict[str, float] | None:
        pos = getattr(obj, "position", None)
        if isinstance(pos, (list, tuple)) and len(pos) == 3:
            return {"x": float(pos[0]), "y": float(pos[1]), "z": float(pos[2])}
        if isinstance(pos, dict) and "x" in pos:
            return pos
        return None

    def get_available_power_w(self, obj) -> int | None:
        if obj.power_capacity_w is None:
            return None
        return obj.power_capacity_w - obj.power_reserved_w - obj.allocated_power_w

    def get_slots_url(self, obj) -> str:
        request = self.context.get("request")
        path = f"/api/labs/stations/{obj.pk}/slots"
        return request.build_absolute_uri(path) if request is not None else path


@embedded_resource
class StationTypeSerializer(AppModelSerializer):
    class Meta:
        model = StationType
        fields = ("id", "name", "created_at", "updated_at")
        read_only_fields = fields


class StationStatusRecordSerializer(AppModelSerializer):
    status = serializers.SerializerMethodField(read_only=True)
    actor = UserReferenceSerializer(source="creator", read_only=True, allow_null=True)

    class Meta:
        model = StationStatusRecord
        fields = ("id", "station", "status", "metadata", "actor", "created_at")
        read_only_fields = fields

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_status(self, obj) -> dict[str, str] | None:
        return to_choice_reference(getattr(obj, "status", None), ResourceLifecycleStatus.choices)


@embedded_resource
class RoomReferenceSerializer(NamedReferenceSerializer):
    """A room item of the station reference-data bundle (REL-15)."""

    sku = serializers.CharField(read_only=True)

    class Meta:
        ref_name = "LabsStationRoomReference"


class StationReferenceDataSerializer(serializers.Serializer):
    types = StationTypeSerializer(many=True, read_only=True)
    bench_types = NamedReferenceSerializer(many=True, read_only=True)
    rooms = RoomReferenceSerializer(many=True, read_only=True)
    statuses = ChoiceReferenceSerializer(many=True, read_only=True, help_text="Deprecated seven-value status.")
    lifecycle_statuses = ChoiceReferenceSerializer(many=True, read_only=True)
    access_policies = ChoiceReferenceSerializer(many=True, read_only=True)
    slot_statuses = ChoiceReferenceSerializer(many=True, read_only=True, help_text="Slot service_status values.")


class StationOptionsQuerySerializer(OptionsQueryMixin):
    room_id = serializers.IntegerField(required=False, min_value=1)
    station_type_id = serializers.IntegerField(required=False, min_value=1)


__all__ = [
    "RoomReferenceSerializer",
    "StationCreateSerializer",
    "StationLifecycleWriteSerializer",
    "StationListQuerySerializer",
    "StationOptionsQuerySerializer",
    "StationPlacementSerializer",
    "StationReferenceDataSerializer",
    "StationSerializer",
    "StationSlotCreateSerializer",
    "StationSlotSerializer",
    "StationSlotUpdateSerializer",
    "StationStatusRecordSerializer",
    "StationStatusWriteSerializer",
    "StationTypeSerializer",
    "StationTypeWriteSerializer",
    "StationUpdateSerializer",
]
