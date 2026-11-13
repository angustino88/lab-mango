"""Explicit room read projections and write requests; serializers never save models."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api.options import OptionsQueryMixin
from core.common.api.summary_serializers import StatusSummarySerializer
from core.labs.features.base.resource_images import ResourceImageURLField
from core.labs.features.base.serializers import (
    AppModelSerializer,
    ChoiceReferenceSerializer,
    NamedReferenceSerializer,
    ResourceOwnerSerializer,
    ResourceWriteSerializerMixin,
    to_choice_reference,
)
from core.labs.features.locations.api.serializers import LocationLifecycleWriteSerializer, LocationStateFieldsMixin
from core.labs.models.resource.base.status import ResourceLifecycleStatus
from core.labs.models.resource.location.room import Room, RoomStatus, RoomStatusRecord
from core.labs.models.resource.location.room_observation import RoomObservation
from core.labs.models.resource.location.room_slot import RoomSlot

from .filters import ROOM_FILTERS


class RoomStatusSummarySerializer(StatusSummarySerializer):
    """The deprecated seven-value status, computed from lifecycle, condition, access and activity."""


class RoomLifecycleWriteSerializer(LocationLifecycleWriteSerializer):
    pass


class RoomCreateSerializer(ResourceWriteSerializerMixin, serializers.ModelSerializer):
    department_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    group_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    owner_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    country_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    city_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    building_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    utilities = serializers.DictField(required=False)

    class Meta:
        model = Room
        fields = (
            "sku",
            "name",
            "label",
            "department_id",
            "group_id",
            "owner_id",
            "remark",
            "map_url",
            "length_m",
            "width_m",
            "country_id",
            "city_id",
            "building_id",
            "floor",
            "layout_rows",
            "layout_columns",
            "usable_height_m",
            "floor_plan_revision",
            "floor_plan_url",
            "max_occupancy",
            "power_capacity_w",
            "cooling_capacity_w",
            "network_port_capacity",
            "utilities",
        )
        validators = []
        extra_kwargs = {"sku": {"validators": []}}


class RoomUpdateSerializer(RoomCreateSerializer):
    class Meta(RoomCreateSerializer.Meta):
        extra_kwargs = {}


class RoomStatusWriteSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    """Deprecated: mapped onto lifecycle, access policy and downtime. ``reserved`` cannot be set."""

    status = serializers.ChoiceField(choices=RoomStatus.choices)
    metadata = serializers.DictField(required=False, default=dict)


class RoomObservationWriteSerializer(ResourceWriteSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = RoomObservation
        fields = ("observed_at", "source", "temperature_c", "humidity_percent", "power_usage_w")
        validators = []


RoomListQuerySerializer = ROOM_FILTERS.serializer("RoomListQuerySerializer")


class RoomSlotSerializer(AppModelSerializer):
    status = serializers.SerializerMethodField(
        read_only=True, help_text="Deprecated: available, occupied, blocked or retired (occupied is computed)."
    )
    service_status = serializers.SerializerMethodField()
    occupied = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = RoomSlot
        fields = (
            "id",
            "room",
            "row_index",
            "col_index",
            "slot_code",
            "slot_type",
            "status",
            "service_status",
            "occupied",
            "x_mm",
            "y_mm",
            "width_mm",
            "depth_mm",
            "orientation_degrees",
            "max_load_kg",
            "power_capacity_w",
            "utilities",
            "is_accessible",
            "clearance_width_mm",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_status(self, obj) -> dict[str, str] | None:
        if obj.status == "usable":
            return to_choice_reference("occupied" if getattr(obj, "occupied", False) else "available")
        return to_choice_reference(obj.status)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_service_status(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.status, RoomSlot.STATUSES)


class RoomStatusRecordSerializer(AppModelSerializer):
    status = serializers.SerializerMethodField(read_only=True)
    actor = ResourceOwnerSerializer(source="creator", read_only=True, allow_null=True)

    class Meta:
        model = RoomStatusRecord
        fields = ("id", "room", "status", "metadata", "actor", "created_at")
        read_only_fields = fields

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_status(self, obj) -> dict[str, str] | None:
        return to_choice_reference(getattr(obj, "status", None), ResourceLifecycleStatus.choices)


class RoomObservationSerializer(AppModelSerializer):
    class Meta:
        model = RoomObservation
        fields = (
            "id",
            "room",
            "observed_at",
            "source",
            "temperature_c",
            "humidity_percent",
            "power_usage_w",
            "created_at",
        )
        read_only_fields = fields


class RoomSerializer(LocationStateFieldsMixin, AppModelSerializer):
    image_url = ResourceImageURLField()
    group = NamedReferenceSerializer(read_only=True, allow_null=True)
    owner = NamedReferenceSerializer(read_only=True, allow_null=True)
    country = NamedReferenceSerializer(read_only=True, allow_null=True)
    city = NamedReferenceSerializer(read_only=True, allow_null=True)
    building = NamedReferenceSerializer(read_only=True, allow_null=True)
    department = NamedReferenceSerializer(read_only=True, allow_null=True)
    location_path = serializers.CharField(source="get_location_path", read_only=True)
    area_m2 = serializers.DecimalField(max_digits=18, decimal_places=6, read_only=True, allow_null=True)
    slot_capacity = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = Room
        fields = (
            "id",
            "uid",
            "sku",
            "name",
            "label",
            "department",
            "group",
            "owner",
            "remark",
            "image",
            "image_url",
            "map_url",
            "length_m",
            "width_m",
            "area_m2",
            "country",
            "city",
            "building",
            "floor",
            "layout_rows",
            "layout_columns",
            "slot_capacity",
            "usable_height_m",
            "coordinate_unit",
            "floor_plan_revision",
            "floor_plan_url",
            *LocationStateFieldsMixin.STATE_FIELDS,
            "max_occupancy",
            "power_capacity_w",
            "cooling_capacity_w",
            "network_port_capacity",
            "utilities",
            "location_path",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class RoomOptionsQuerySerializer(OptionsQueryMixin):
    building_id = serializers.IntegerField(required=False, min_value=1)
    city_id = serializers.IntegerField(required=False, min_value=1)


__all__ = [
    "RoomCreateSerializer",
    "RoomLifecycleWriteSerializer",
    "RoomListQuerySerializer",
    "RoomObservationSerializer",
    "RoomObservationWriteSerializer",
    "RoomOptionsQuerySerializer",
    "RoomSerializer",
    "RoomSlotSerializer",
    "RoomStatusRecordSerializer",
    "RoomStatusWriteSerializer",
    "RoomUpdateSerializer",
]
