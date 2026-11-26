"""Request and response contracts for flat graphic placement mappings.

References between collections use the id form (REL-16): the client joins them inside this response.
"""

from rest_framework import serializers

from core.common.api.summary_serializers import embedded_resource


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


class MappingConditionsSerializer(serializers.Serializer):
    """Current conditions from fresh telemetry placed in the room or station; null when nothing reports."""

    temperature_c = serializers.FloatField(allow_null=True, help_text="Mean of current temperature channels.")
    humidity_percent = serializers.FloatField(allow_null=True, help_text="Mean of current humidity channels.")
    power_w = serializers.FloatField(allow_null=True, help_text="Sum of current power channels.")
    observed_at = serializers.DateTimeField(allow_null=True, help_text="Newest reading included.")
    channel_count = serializers.IntegerField()


@embedded_resource
class MappingRoomSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    uid = serializers.UUIDField(label="UID")
    sku = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    layout_rows = serializers.IntegerField(allow_null=True)
    layout_columns = serializers.IntegerField(allow_null=True)
    length_m = serializers.DecimalField(max_digits=8, decimal_places=2, allow_null=True, required=False)
    width_m = serializers.DecimalField(max_digits=8, decimal_places=2, allow_null=True, required=False)
    conditions = MappingConditionsSerializer(allow_null=True, required=False)


@embedded_resource
class MappingRoomSlotSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    room_id = serializers.IntegerField()
    row_index = serializers.IntegerField()
    col_index = serializers.IntegerField()
    slot_code = serializers.CharField()
    x_mm = serializers.IntegerField(allow_null=True)
    y_mm = serializers.IntegerField(allow_null=True)
    width_mm = serializers.IntegerField(allow_null=True)
    depth_mm = serializers.IntegerField(allow_null=True)
    orientation_degrees = serializers.IntegerField()
    slot_type = serializers.CharField(required=False, help_text="station, storage, aisle, safety, utility or reserved.")
    status = serializers.CharField(required=False, help_text="usable, blocked or retired.")


class MappingStationLayoutSerializer(serializers.Serializer):
    width_mm = serializers.IntegerField(allow_null=True)
    depth_mm = serializers.IntegerField(allow_null=True)
    height_mm = serializers.IntegerField(allow_null=True)
    orientation_degrees = serializers.IntegerField(allow_null=True)


class MappingStationCapacitySerializer(serializers.Serializer):
    bench_capacity = serializers.IntegerField(allow_null=True)
    rack_units = serializers.IntegerField(allow_null=True)
    rack_units_used = serializers.IntegerField(required=False)
    power_capacity_w = serializers.IntegerField(allow_null=True)
    power_reserved_w = serializers.IntegerField(allow_null=True)
    power_installed_w = serializers.FloatField(required=False, help_text="Rated draw of equipment installed here.")
    max_load_kg = serializers.IntegerField(allow_null=True)
    load_installed_kg = serializers.FloatField(required=False)
    network_port_capacity = serializers.IntegerField(allow_null=True)
    installed_units = serializers.IntegerField(required=False)


class MappingRackItemSerializer(serializers.Serializer):
    equipment_id = serializers.IntegerField()
    sku = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    category = serializers.CharField(allow_null=True)
    power_draw_w = serializers.IntegerField(allow_null=True)
    rack_unit = serializers.IntegerField()
    rack_unit_height = serializers.IntegerField()
    rack_face = serializers.CharField()


@embedded_resource
class MappingStationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    uid = serializers.UUIDField(label="UID")
    sku = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    room_id = serializers.IntegerField(allow_null=True)
    slot_id = serializers.IntegerField(allow_null=True)
    visual_model_id = serializers.IntegerField(
        allow_null=True, required=False, help_text="3D library model shown for this resource, after catalog defaults."
    )
    layout = MappingStationLayoutSerializer(required=False)
    capacity = MappingStationCapacitySerializer(required=False)
    conditions = MappingConditionsSerializer(allow_null=True, required=False)
    rack = MappingRackItemSerializer(many=True, required=False, help_text="Rack-mounted equipment, bottom unit first.")


@embedded_resource
class MappingStationSlotSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    station_id = serializers.IntegerField()
    position_index = serializers.IntegerField()
    slot_code = serializers.CharField()

    def get_fields(self):
        fields = super().get_fields()
        fields["label"] = serializers.CharField(allow_blank=True)
        fields["width_mm"] = serializers.IntegerField(allow_null=True, required=False)
        return fields


@embedded_resource
class MappingBenchSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    uid = serializers.UUIDField(label="UID")
    sku = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    setup_location_id = serializers.IntegerField(allow_null=True)
    station_slot_id = serializers.IntegerField(allow_null=True)
    visual_model_id = serializers.IntegerField(
        allow_null=True, required=False, help_text="3D library model shown for this resource, after catalog defaults."
    )


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
    product_model = MappingEquipmentCategorySerializer(allow_null=True, required=False)
    bench_id = serializers.IntegerField(allow_null=True)
    bench_assignment = MappingEquipmentAssignmentSerializer(allow_null=True)
    visual_model_id = serializers.IntegerField(
        allow_null=True, required=False, help_text="3D library model shown for this resource, after catalog defaults."
    )


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
    equipment_id = serializers.IntegerField()
    license_id = serializers.IntegerField()
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


_MAPPING_STATE_CHOICES = (
    ("fully_mapped", "Fully mapped"),
    ("needs_equipment", "Needs equipment"),
    ("needs_placement", "Needs placement"),
)


class BenchMappingListQuerySerializer(serializers.Serializer):
    """Allowlisted query of the bench mapping list (COL-3, COL-4)."""

    q = serializers.CharField(
        required=False,
        max_length=100,
        help_text="Matches the SKU or name of the bench, its station, its room or a unit placed on it.",
    )
    room_id = serializers.IntegerField(required=False, min_value=1)
    station_id = serializers.IntegerField(required=False, min_value=1)
    bench_id = serializers.IntegerField(required=False, min_value=1)
    equipment_category_id = serializers.IntegerField(
        required=False, min_value=1, help_text="Benches with at least one unit of this equipment category."
    )
    state = serializers.ChoiceField(
        choices=_MAPPING_STATE_CHOICES,
        required=False,
        help_text="needs_placement: no station in a room. needs_equipment: placed, no units. fully_mapped: both.",
    )
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100, default=25)


class BenchMappingSummarySerializer(serializers.Serializer):
    benches = serializers.IntegerField(min_value=0, help_text="Benches matching the filters (state not applied).")
    fully_mapped = serializers.IntegerField(min_value=0)
    needs_equipment = serializers.IntegerField(min_value=0)
    needs_placement = serializers.IntegerField(min_value=0)
    equipment = serializers.IntegerField(min_value=0, help_text="Units placed on those benches.")


class BenchMappingPageSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=0)
    page = serializers.IntegerField(min_value=1)
    page_size = serializers.IntegerField(min_value=1)
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)


class BenchMappingListMetaSerializer(serializers.Serializer):
    pagination = BenchMappingPageSerializer()
    summary = BenchMappingSummarySerializer()


class BenchMappingListResponseSerializer(serializers.Serializer):
    """A page of benches (``data.benches``) and only the rows they reference in the other collections."""

    def get_fields(self):
        fields = super().get_fields()
        fields["data"] = ResourceMappingDataSerializer()
        fields["meta"] = BenchMappingListMetaSerializer()
        return fields


__all__ = (
    "BenchMappingListQuerySerializer",
    "BenchMappingListResponseSerializer",
    "ResourceMappingQuerySerializer",
    "ResourceMappingResponseSerializer",
)
