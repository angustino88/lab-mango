"""Explicit transport fields; all domain writes go through commands."""

from datetime import timezone
from typing import Any
from urllib.parse import urlencode

from drf_api_contracts.serializers import PaginationMetadataSerializer
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api.options import OptionsQueryMixin
from core.common.api.summary_serializers import StatusSummarySerializer
from core.labs.features.base.serializers import (
    AppModelSerializer,
    ChoiceReferenceSerializer,
    NamedReferenceSerializer,
    ResourceWriteSerializerMixin,
    UIDNamedReferenceSerializer,
    to_choice_reference,
)
from core.labs.models import Bench, BenchFavorite, BenchGroup, BenchType

from .filters import BENCH_FILTERS


class BenchStatusSummarySerializer(StatusSummarySerializer):
    """Lifecycle status, not booking status or live activity."""


class StrictWriteMixin(ResourceWriteSerializerMixin):
    """Preserve the benches module's established strict-write helper."""


class BenchCreateSerializer(StrictWriteMixin, serializers.ModelSerializer):
    department_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    group_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    owner_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    type_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    bench_group_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    setup_location_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    station_slot_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    required_utilities = serializers.DictField(required=False)

    class Meta:
        model = Bench
        fields = (
            "sku",
            "name",
            "department_id",
            "group_id",
            "owner_id",
            "remark",
            "image",
            "type_id",
            "bench_group_id",
            "description",
            "documentation_url",
            "setup_location_id",
            "station_slot_id",
            "criticality",
            "requested_power_w",
            "requested_load_kg",
            "requested_cooling_w",
            "required_utilities",
            "commissioning_date",
            "last_inspected_at",
            "next_inspection_due_at",
        )
        validators = []
        extra_kwargs = {"sku": {"validators": []}}


class BenchUpdateSerializer(BenchCreateSerializer):
    class Meta(BenchCreateSerializer.Meta):
        extra_kwargs = {}

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not self.partial:
            for field_name in self.fields:
                if self.fields[field_name].read_only or field_name == "sku":
                    continue
                try:
                    default = self.fields[field_name].get_default()
                except serializers.SkipField:
                    default = None
                attrs.setdefault(field_name, default)
        return attrs


class BenchPlacementSerializer(StrictWriteMixin, serializers.Serializer):
    setup_location_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    station_slot_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide at least one placement field.")
        if (
            "setup_location_id" in attrs
            and attrs["setup_location_id"] is None
            and attrs.get("station_slot_id") is not None
        ):
            raise serializers.ValidationError({"station_slot_id": "A slot requires a setup location."})
        return attrs


BenchListQuerySerializer = BENCH_FILTERS.serializer("BenchListQuerySerializer")


class BenchEquipmentReferenceSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    uid = serializers.UUIDField(read_only=True)
    sku = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    kind = NamedReferenceSerializer(read_only=True, allow_null=True)


class BenchSetupEquipmentSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    equipment = BenchEquipmentReferenceSerializer(read_only=True)
    role = serializers.CharField(read_only=True)
    position = serializers.IntegerField(read_only=True)
    is_monitored = serializers.BooleanField(source="monitor", read_only=True)
    assigned_at = serializers.DateTimeField(read_only=True)


class BenchEquipmentListQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False)


class BenchSerializer(AppModelSerializer):
    group = NamedReferenceSerializer(read_only=True, allow_null=True)
    department = NamedReferenceSerializer(read_only=True, allow_null=True)
    owner = NamedReferenceSerializer(read_only=True, allow_null=True)
    type = NamedReferenceSerializer(read_only=True, allow_null=True)
    bench_group = NamedReferenceSerializer(read_only=True, allow_null=True)
    setup_location = UIDNamedReferenceSerializer(read_only=True, allow_null=True)
    station_slot = NamedReferenceSerializer(read_only=True, allow_null=True)
    status = serializers.SerializerMethodField(read_only=True)
    setup_location_path = serializers.CharField(read_only=True)
    is_favorite = serializers.BooleanField(read_only=True)
    equipment_count = serializers.SerializerMethodField(read_only=True)
    equipment_url = serializers.SerializerMethodField()

    class Meta:
        model = Bench
        fields = (
            "id",
            "uid",
            "sku",
            "name",
            "group",
            "department",
            "owner",
            "remark",
            "image",
            "type",
            "bench_group",
            "description",
            "documentation_url",
            "setup_location",
            "station_slot",
            "status",
            "criticality",
            "requested_power_w",
            "requested_load_kg",
            "requested_cooling_w",
            "required_utilities",
            "commissioning_date",
            "last_inspected_at",
            "next_inspection_due_at",
            "created_at",
            "updated_at",
            "setup_location_path",
            "is_favorite",
            "equipment_count",
            "equipment_url",
        )
        read_only_fields = fields

    def get_equipment_count(self, obj) -> int:
        return getattr(obj, "equipment_count", 0)

    def get_equipment_url(self, obj) -> str:
        return f"/api/labs/benches/{obj.pk}/equipment/"

    @extend_schema_field(ChoiceReferenceSerializer(allow_null=True))
    def get_status(self, obj) -> dict[str, str] | None:
        raw_status = getattr(obj, "lifecycle_status", None)
        return to_choice_reference(raw_status, Bench.LIFECYCLE_STATUSES)


class BenchResourceDetailSerializer(BenchSerializer):
    """Lean resource detail projection with a link matching the slashless route."""

    def get_equipment_url(self, obj) -> str:
        return f"/api/labs/benches/{obj.pk}/equipment"


class BenchComputingActivitySerializer(serializers.Serializer):
    status = ChoiceReferenceSerializer(read_only=True)
    last_agent_report_at = serializers.DateTimeField(read_only=True, allow_null=True, default_timezone=timezone.utc)
    is_stale = serializers.BooleanField(
        read_only=True,
        allow_null=True,
        help_text="Heartbeat strictly older than ten minutes at booking_summary.evaluated_at; null if unknown.",
    )


class BenchDetailEquipmentSerializer(BenchSetupEquipmentSerializer):
    computing_activity = BenchComputingActivitySerializer(read_only=True, allow_null=True)


class BenchEquipmentPageMetaSerializer(serializers.Serializer):
    pagination = PaginationMetadataSerializer(read_only=True)


class BenchEquipmentPageSerializer(serializers.Serializer):
    assignments = serializers.ListField(child=BenchDetailEquipmentSerializer(), max_length=100, read_only=True)
    meta = BenchEquipmentPageMetaSerializer(read_only=True)

    def get_fields(self):
        fields = super().get_fields()
        fields["data"] = fields.pop("assignments")
        return fields


class BenchReservationSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    booking_code = serializers.CharField(read_only=True)
    starts_at = serializers.DateTimeField(read_only=True, default_timezone=timezone.utc)
    ends_at = serializers.DateTimeField(read_only=True, default_timezone=timezone.utc)
    status = ChoiceReferenceSerializer(read_only=True)
    approval_status = ChoiceReferenceSerializer(read_only=True)
    project = NamedReferenceSerializer(read_only=True, allow_null=True)


class BenchBookingSummarySerializer(serializers.Serializer):
    """Active reserving bookings, current half-open windows and earliest future start; ties by ID."""

    evaluated_at = serializers.DateTimeField(read_only=True, default_timezone=timezone.utc)
    current_reservations = serializers.ListField(child=BenchReservationSerializer(), max_length=5, read_only=True)
    current_reservations_count = serializers.IntegerField(read_only=True)
    is_current_reservations_complete = serializers.BooleanField(read_only=True)
    next_reservation = BenchReservationSerializer(read_only=True, allow_null=True)


class BenchDetailSerializer(BenchResourceDetailSerializer):
    """Internal serialization for the retained bounded operational read projection."""

    equipment = serializers.SerializerMethodField(read_only=True)
    booking_summary = BenchBookingSummarySerializer(read_only=True)

    class Meta:
        model = Bench
        fields = (*BenchSerializer.Meta.fields, "equipment", "booking_summary")
        read_only_fields = fields

    @extend_schema_field(BenchEquipmentPageSerializer)
    def get_equipment(self, obj) -> dict[str, Any]:
        page = obj.equipment_page

        def link(number: int) -> str:
            return f"/api/labs/benches/{obj.pk}?" + urlencode(
                {
                    "equipment_page": number,
                    "equipment_page_size": page.paginator.per_page,
                }
            )

        return BenchEquipmentPageSerializer(
            {
                "data": page.object_list,
                "meta": {
                    "pagination": {
                        "count": page.paginator.count,
                        "page": page.number,
                        "page_size": page.paginator.per_page,
                        "next": link(page.next_page_number()) if page.has_next() else None,
                        "previous": link(page.previous_page_number()) if page.has_previous() else None,
                    }
                },
            },
            context=self.context,
        ).data


class BenchSelectQuerySerializer(OptionsQueryMixin):
    """Query parameter validation for bench selector options endpoint."""

    bench_group_id = serializers.IntegerField(required=False, min_value=1)
    type_id = serializers.IntegerField(required=False, min_value=1)
    setup_location_id = serializers.IntegerField(required=False, min_value=1)
    lifecycle_status = serializers.CharField(required=False)
    favorite = serializers.BooleanField(required=False)


class BenchFavoriteSerializer(AppModelSerializer):
    bench = UIDNamedReferenceSerializer(read_only=True)

    class Meta:
        model = BenchFavorite
        fields = ("id", "bench", "created_at")
        read_only_fields = fields


class BenchReferenceWriteSerializer(StrictWriteMixin, serializers.Serializer):
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(source="active", required=False)


class BenchGroupSerializer(AppModelSerializer):
    is_active = serializers.BooleanField(source="active", read_only=True)

    class Meta:
        model = BenchGroup
        fields = ("id", "name", "description", "is_active", "created_at", "updated_at")
        read_only_fields = fields


class BenchTypeSerializer(AppModelSerializer):
    is_active = serializers.BooleanField(source="active", read_only=True)

    class Meta:
        model = BenchType
        fields = ("id", "name", "description", "is_active", "created_at", "updated_at")
        read_only_fields = fields


class BenchStationReferenceSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    uid = serializers.UUIDField(read_only=True)
    sku = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class BenchReferenceDataSerializer(serializers.Serializer):
    types = BenchTypeSerializer(many=True, read_only=True)
    groups = BenchGroupSerializer(many=True, read_only=True)
    stations = BenchStationReferenceSerializer(many=True, read_only=True)
    lifecycle_statuses = ChoiceReferenceSerializer(many=True, read_only=True)
