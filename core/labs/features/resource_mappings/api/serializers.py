"""Request and response contracts for flat graphic placement mappings."""

from rest_framework import serializers

from core.common.api.summary_serializers import embedded_resource
from core.labs.features.base.serializers import NamedReferenceSerializer


class ResourceMappingQuerySerializer(serializers.Serializer):
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False, default=25)
    rooms_cursor = serializers.CharField(required=False)
    room_slots_cursor = serializers.CharField(required=False)
    stations_cursor = serializers.CharField(required=False)
    station_slots_cursor = serializers.CharField(required=False)
    benches_cursor = serializers.CharField(required=False)
    equipment_cursor = serializers.CharField(required=False)
    licenses_cursor = serializers.CharField(required=False)
    license_assignments_cursor = serializers.CharField(required=False)


@embedded_resource
class MappingRoomSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    uid = serializers.UUIDField(label="UID")
    sku = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    layout_rows = serializers.IntegerField(allow_null=True)
    layout_columns = serializers.IntegerField(allow_null=True)


@embedded_resource
class MappingRoomSlotSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    room = NamedReferenceSerializer()
    row_index = serializers.IntegerField()
    col_index = serializers.IntegerField()
    slot_code = serializers.CharField()
    x_mm = serializers.IntegerField(allow_null=True)
    y_mm = serializers.IntegerField(allow_null=True)
    width_mm = serializers.IntegerField(allow_null=True)
    depth_mm = serializers.IntegerField(allow_null=True)
    orientation_degrees = serializers.IntegerField()


@embedded_resource
class MappingStationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    uid = serializers.UUIDField(label="UID")
    sku = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    room = NamedReferenceSerializer(allow_null=True)
    slot = NamedReferenceSerializer(allow_null=True)


@embedded_resource
class MappingStationSlotSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    station = NamedReferenceSerializer()
    position_index = serializers.IntegerField()
    slot_code = serializers.CharField()
    def get_fields(self):
        fields = super().get_fields()
        fields["label"] = serializers.CharField(allow_blank=True)
        return fields


@embedded_resource
class MappingBenchSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    uid = serializers.UUIDField(label="UID")
    sku = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    setup_location = NamedReferenceSerializer(allow_null=True)
    station_slot = NamedReferenceSerializer(allow_null=True)


class MappingEquipmentCategorySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField(allow_blank=True)


class MappingLicenseCategorySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField(allow_blank=True, allow_null=True)


@embedded_resource
class MappingEquipmentAssignmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    role = serializers.CharField()
    position = serializers.IntegerField()
    is_monitored = serializers.BooleanField()
    assigned_at = serializers.DateTimeField()


@embedded_resource
class MappingEquipmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    uid = serializers.UUIDField(label="UID")
    sku = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    category = MappingEquipmentCategorySerializer(allow_null=True)
    bench = NamedReferenceSerializer(allow_null=True)
    bench_assignment = MappingEquipmentAssignmentSerializer(allow_null=True)


@embedded_resource
class MappingLicenseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    uid = serializers.UUIDField(label="UID")
    sku = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    category = MappingLicenseCategorySerializer(allow_null=True)


@embedded_resource
class MappingLicenseAssignmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    equipment = NamedReferenceSerializer()
    license = NamedReferenceSerializer()
    assigned_at = serializers.DateTimeField()


class MappingPaginationSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=0)
    page_size = serializers.IntegerField(min_value=1)
    next_cursor = serializers.CharField(allow_null=True)
    previous_cursor = serializers.CharField(allow_null=True)


class ResourceMappingPaginationSerializer(serializers.Serializer):
    rooms = MappingPaginationSerializer()
    room_slots = MappingPaginationSerializer()
    stations = MappingPaginationSerializer()
    station_slots = MappingPaginationSerializer()
    benches = MappingPaginationSerializer()
    equipment = MappingPaginationSerializer()
    licenses = MappingPaginationSerializer()
    license_assignments = MappingPaginationSerializer()


class ResourceMappingMetaSerializer(serializers.Serializer):
    pagination = ResourceMappingPaginationSerializer()


class ResourceMappingDataSerializer(serializers.Serializer):
    rooms = MappingRoomSerializer(many=True)
    room_slots = MappingRoomSlotSerializer(many=True)
    stations = MappingStationSerializer(many=True)
    station_slots = MappingStationSlotSerializer(many=True)
    benches = MappingBenchSerializer(many=True)
    equipment = MappingEquipmentSerializer(many=True)
    licenses = MappingLicenseSerializer(many=True)
    license_assignments = MappingLicenseAssignmentSerializer(many=True)


class ResourceMappingResponseSerializer(serializers.Serializer):
    """Response envelope with runtime reserved keys declared dynamically for schema generation."""

    def get_fields(self):
        fields = super().get_fields()
        fields["data"] = ResourceMappingDataSerializer()
        fields["meta"] = ResourceMappingMetaSerializer()
        return fields


__all__ = (
    "ResourceMappingQuerySerializer",
    "ResourceMappingResponseSerializer",
)
