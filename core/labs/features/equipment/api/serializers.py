from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from core.common.api.options import OptionsQueryMixin
from core.common.api.summary_serializers import StatusSummarySerializer
from core.labs.features.base.serializers import (
    AppModelSerializer,
    ChoiceReferenceSerializer,
    MoneySerializer,
    NamedReferenceSerializer,
    ResourceWriteSerializerMixin,
    UIDNamedReferenceSerializer,
    to_choice_reference,
    to_money,
)
from core.labs.features.equipment.api.capabilities import EQUIPMENT_CAPABILITIES
from core.labs.models import (
    Equipment,
    EquipmentCategory,
    EquipmentKind,
    EquipmentManufacturer,
    EquipmentProductModel,
    EquipmentStatus,
    EquipmentStatusRecord,
    EquipmentType,
    ProductModelSpecification,
    SpecificationDefinition,
)
from core.labs.models.resource.base.resource import Department, ResourceGroup
from core.labs.models.resource.equipment.assignment import LOCATION_NOTE_MAX_LENGTH, EquipmentAssignment


@extend_schema_serializer(component_name="EquipmentInventoryStatusSummary")
class EquipmentStatusSummarySerializer(StatusSummarySerializer):
    """Latest equipment lifecycle state, distinct from live activity."""


class ComputingActivitySummarySerializer(StatusSummarySerializer):
    """Stored live activity, including assets without telemetry as unknown."""


class EquipmentPlacementSerializer(serializers.Serializer):
    """Where a unit is now: exactly one of bench, station, room, or only ``location_note``."""

    id = serializers.IntegerField(read_only=True)
    target_type = serializers.ChoiceField(
        choices=("bench", "station", "room", "note"),
        read_only=True,
        help_text="Which target is set; ``note`` means an untracked place described by location_note.",
    )
    bench = UIDNamedReferenceSerializer(read_only=True, allow_null=True)
    station = UIDNamedReferenceSerializer(read_only=True, allow_null=True)
    room = UIDNamedReferenceSerializer(read_only=True, allow_null=True)
    location_note = serializers.CharField(read_only=True)
    role = serializers.CharField(read_only=True)
    position = serializers.IntegerField(read_only=True)
    placed_at = serializers.DateTimeField(source="assigned_at", read_only=True)

    class Meta:
        ref_name = "EquipmentPlacement"


class EquipmentSerializer(AppModelSerializer):
    category = NamedReferenceSerializer(source="kind.category", read_only=True)
    kind = NamedReferenceSerializer(read_only=True)
    type = NamedReferenceSerializer(read_only=True, allow_null=True)
    manufacturer = NamedReferenceSerializer(read_only=True, allow_null=True)
    product_model = NamedReferenceSerializer(read_only=True, allow_null=True)
    owner = NamedReferenceSerializer(read_only=True, allow_null=True)
    department = NamedReferenceSerializer(read_only=True, allow_null=True)
    group = NamedReferenceSerializer(read_only=True, allow_null=True)
    last_calibrated_at = serializers.DateTimeField(read_only=True, allow_null=True)
    next_calibration_due_at = serializers.DateTimeField(read_only=True, allow_null=True)
    calibration_overdue = serializers.BooleanField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)
    acquisition_price = serializers.SerializerMethodField(read_only=True)
    placement = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Equipment
        fields = (
            "id",
            "uid",
            "category",
            "kind",
            "type",
            "sku",
            "name",
            "manufacturer",
            "product_model",
            "serial_number",
            "log_label",
            "owner",
            "department",
            "group",
            "placement",
            "firmware_version",
            "power_draw_w",
            "weight_kg",
            "warranty_until",
            "calibration_required",
            "last_calibrated_at",
            "next_calibration_due_at",
            "calibration_overdue",
            "metadata",
            "replacement_date",
            "status",
            "acquisition_price",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(MoneySerializer(allow_null=True))
    def get_acquisition_price(self, obj):
        amount = getattr(obj, "acquisition_price", None)
        currency = getattr(obj, "acquisition_currency", None)
        return to_money(amount, currency)

    @extend_schema_field(EquipmentPlacementSerializer(allow_null=True))
    def get_placement(self, obj) -> dict | None:
        """Active placement from the list projection's prefetch; ``null`` when the location is unknown."""
        placements = getattr(obj, "active_placements", None)
        if placements is None:  # instance not built by an equipment projection
            placements = list(
                EquipmentAssignment.all_placements.filter(equipment_id=obj.pk, unassigned_at__isnull=True).select_related(
                    "bench", "station", "room"
                )
            )
        return EquipmentPlacementSerializer(placements[0], context=self.context).data if placements else None

    @extend_schema_field(ChoiceReferenceSerializer(allow_null=True))
    def get_status(self, obj) -> dict[str, str] | None:
        raw_status = getattr(obj, "current_status", None)
        return to_choice_reference(raw_status, EquipmentStatus.choices)


class EquipmentCreateSerializer(ResourceWriteSerializerMixin, serializers.ModelSerializer):
    kind_id = serializers.IntegerField(source="kind", min_value=1)
    type_id = serializers.IntegerField(source="type", min_value=1, allow_null=True, required=False)
    manufacturer_id = serializers.IntegerField(source="manufacturer", min_value=1, allow_null=True, required=False)
    product_model_id = serializers.IntegerField(source="product_model", min_value=1, allow_null=True, required=False)
    owner_id = serializers.IntegerField(source="owner", min_value=1, allow_null=True, required=False)
    department_id = serializers.IntegerField(source="department", min_value=1, allow_null=True, required=False)
    group_id = serializers.IntegerField(source="group", min_value=1, allow_null=True, required=False)

    class Meta:
        model = Equipment
        fields = (
            "kind_id",
            "type_id",
            "manufacturer_id",
            "product_model_id",
            "owner_id",
            "department_id",
            "group_id",
            "sku",
            "name",
            "serial_number",
            "log_label",
            "details",
            "metadata",
            "replacement_date",
            "firmware_version",
            "power_draw_w",
            "weight_kg",
            "warranty_until",
            "calibration_required",
        )
        extra_kwargs = {"sku": {"validators": []}}


class EquipmentAssignmentSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    bench_id = serializers.IntegerField(min_value=1)
    role = serializers.CharField(max_length=64, required=False, default="default")
    position = serializers.IntegerField(min_value=0, required=False, default=0)


class CommonStatusDetailsSerializer(serializers.Serializer):
    responsible_person = serializers.CharField(max_length=255)
    notes = serializers.CharField(
        max_length=2000,
        required=False,
        allow_blank=True,
        default="",
    )


class AvailableStatusDetailsSerializer(CommonStatusDetailsSerializer):
    pass


class InUseStatusDetailsSerializer(CommonStatusDetailsSerializer):
    bench_id = serializers.IntegerField(min_value=1)


class InStorageStatusDetailsSerializer(CommonStatusDetailsSerializer):
    location = serializers.CharField(max_length=255)
    stored_date = serializers.DateField()
    condition = serializers.CharField(max_length=255)


class TransferredStatusDetailsSerializer(CommonStatusDetailsSerializer):
    destination = serializers.CharField(max_length=255)
    transfer_date = serializers.DateField()
    reason = serializers.CharField(max_length=2000)
    condition = serializers.CharField(max_length=255)


class MaintenanceStatusDetailsSerializer(CommonStatusDetailsSerializer):
    reason = serializers.CharField(max_length=2000)
    start_date = serializers.DateField()
    expected_end_date = serializers.DateField(
        required=False,
        allow_null=True,
    )

    def validate(self, attrs):
        start_date = attrs["start_date"]
        end_date = attrs.get("expected_end_date")

        if end_date is not None and end_date < start_date:
            raise serializers.ValidationError({"expected_end_date": "Must be on or after start_date."})

        return attrs


class BorrowedStatusDetailsSerializer(CommonStatusDetailsSerializer):
    borrower = serializers.CharField(max_length=255)
    borrow_date = serializers.DateField()
    expected_return_date = serializers.DateField()
    purpose = serializers.CharField(max_length=2000)
    condition = serializers.CharField(max_length=255)

    def validate(self, attrs):
        borrow_date = attrs["borrow_date"]
        return_date = attrs["expected_return_date"]

        if return_date < borrow_date:
            raise serializers.ValidationError({"expected_return_date": "Must be on or after borrow_date."})

        return attrs


class BrokenStatusDetailsSerializer(CommonStatusDetailsSerializer):
    issue_description = serializers.CharField(max_length=2000)
    issue_date = serializers.DateField()
    failure_cause = serializers.CharField(
        max_length=2000,
        required=False,
        allow_blank=True,
        default="",
    )


class LostStatusDetailsSerializer(CommonStatusDetailsSerializer):
    last_known_location = serializers.CharField(max_length=255)
    reported_date = serializers.DateField()
    description = serializers.CharField(max_length=2000)


class OnOrderStatusDetailsSerializer(CommonStatusDetailsSerializer):
    expected_delivery_date = serializers.DateField(required=False, allow_null=True)
    supplier = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class EquipmentStatusSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    status = serializers.ChoiceField(choices=EquipmentStatus.choices)
    details = serializers.DictField(required=False, default=dict)

    def validate(self, attrs):
        status = attrs["status"]
        details_serializer = {
            EquipmentStatus.AVAILABLE: AvailableStatusDetailsSerializer,
            EquipmentStatus.IN_USE: InUseStatusDetailsSerializer,
            EquipmentStatus.IN_STORAGE: InStorageStatusDetailsSerializer,
            EquipmentStatus.TRANSFERRED: TransferredStatusDetailsSerializer,
            EquipmentStatus.MAINTENANCE: MaintenanceStatusDetailsSerializer,
            EquipmentStatus.BORROWED: BorrowedStatusDetailsSerializer,
            EquipmentStatus.BROKEN: BrokenStatusDetailsSerializer,
            EquipmentStatus.LOST: LostStatusDetailsSerializer,
            EquipmentStatus.ON_ORDER: OnOrderStatusDetailsSerializer,
        }.get(status)
        if details_serializer is None:
            raise serializers.ValidationError({"status": "Unsupported equipment status."})
        details_serializer = details_serializer(data=attrs.get("details") or {})
        details_serializer.is_valid(raise_exception=True)
        attrs["details"] = details_serializer.validated_data
        return attrs


EquipmentStatusOpenApiSerializer = PolymorphicProxySerializer(
    component_name="EquipmentStatusRequest",
    resource_type_field_name="status",
    serializers=[
        EquipmentStatusSerializer,
    ],
)


class EquipmentCategorySerializer(AppModelSerializer):
    capabilities = serializers.SerializerMethodField()

    class Meta:
        model = EquipmentCategory
        fields = ("name", "definition", "capabilities")

    @extend_schema_field({"type": "array", "items": {"type": "string"}})
    def get_capabilities(self, obj):
        return list(EQUIPMENT_CAPABILITIES)


class EquipmentKindSerializer(AppModelSerializer):
    class Meta:
        model = EquipmentKind
        fields = ("id", "category", "name")


class EquipmentTypeSerializer(AppModelSerializer):
    class Meta:
        model = EquipmentType
        fields = ("id", "kind", "name")


class EquipmentManufacturerSerializer(AppModelSerializer):
    class Meta:
        model = EquipmentManufacturer
        fields = ("id", "name")


class ProductModelSpecificationSerializer(AppModelSerializer):
    name = serializers.CharField(source="definition.name", read_only=True)
    unit = serializers.CharField(source="definition.unit", read_only=True)
    value_type = serializers.CharField(source="definition.value_type", read_only=True)

    class Meta:
        model = ProductModelSpecification
        fields = ("id", "definition_id", "name", "unit", "value_type", "value")


class SpecificationDefinitionSerializer(AppModelSerializer):
    class Meta:
        model = SpecificationDefinition
        fields = ("id", "name", "category_id", "unit", "value_type")


class EquipmentProductModelSerializer(AppModelSerializer):
    specifications = ProductModelSpecificationSerializer(many=True, read_only=True)

    class Meta:
        model = EquipmentProductModel
        fields = (
            "id",
            "manufacturer",
            "name",
            "default_power_draw_w",
            "default_weight_kg",
            "specifications",
        )


class EquipmentReferenceDataSerializer(serializers.Serializer):
    categories = EquipmentCategorySerializer(many=True, read_only=True)
    kinds = EquipmentKindSerializer(many=True, read_only=True)
    types = EquipmentTypeSerializer(many=True, read_only=True)
    manufacturers = EquipmentManufacturerSerializer(many=True, read_only=True)
    product_models = EquipmentProductModelSerializer(many=True, read_only=True)
    specification_definitions = SpecificationDefinitionSerializer(many=True, read_only=True)


class EquipmentAssignmentResultSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    equipment = UIDNamedReferenceSerializer(read_only=True)
    bench = UIDNamedReferenceSerializer(read_only=True)
    role = serializers.CharField(read_only=True)
    position = serializers.IntegerField(read_only=True)


class EquipmentPlacementWriteSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    """Set one target, or none with a location note. Role and position apply to benches only."""

    bench_id = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    station_id = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    room_id = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    location_note = serializers.CharField(
        max_length=LOCATION_NOTE_MAX_LENGTH,
        required=False,
        allow_blank=True,
        default="",
        help_text="Required when no target is set; otherwise an optional detail such as a shelf. Trimmed.",
    )
    role = serializers.CharField(max_length=64, required=False, default="default")
    position = serializers.IntegerField(min_value=0, required=False, default=0)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        targets = [name for name in ("bench_id", "station_id", "room_id") if attrs.get(name) is not None]
        if len(targets) > 1:
            raise serializers.ValidationError(
                {"non_field_errors": "Choose one target: bench, station, room, or a location note."}
            )
        if not targets and not attrs.get("location_note", "").strip():
            raise serializers.ValidationError(
                {"location_note": "Describe where the equipment is when no target is chosen."}
            )
        return attrs


class EquipmentStatusRecordSerializer(AppModelSerializer):
    status = serializers.SerializerMethodField(read_only=True)
    metadata = serializers.DictField(read_only=True)

    class Meta:
        model = EquipmentStatusRecord
        fields = ("id", "equipment", "status", "metadata", "created_at")
        read_only_fields = fields

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_status(self, obj) -> dict[str, str] | None:
        return to_choice_reference(getattr(obj, "status", None), EquipmentStatus.choices)


class DepartmentSerializer(AppModelSerializer):
    class Meta:
        model = Department
        fields = ("id", "name", "active", "created_at", "updated_at")
        ref_name = "DepartmentCatalogItem"


class ResourceGroupCatalogSerializer(AppModelSerializer):
    department = DepartmentSerializer(read_only=True)
    department_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = ResourceGroup
        fields = ("id", "name", "department", "department_id", "active", "created_at", "updated_at")
        ref_name = "ResourceGroupCatalogItem"


class EquipmentKindOptionsQuerySerializer(OptionsQueryMixin):
    category_id = serializers.IntegerField(required=False, min_value=1)


class EquipmentTypeOptionsQuerySerializer(OptionsQueryMixin):
    kind_id = serializers.IntegerField(required=False, min_value=1)
    category_id = serializers.IntegerField(required=False, min_value=1)


class EquipmentManufacturerOptionsQuerySerializer(OptionsQueryMixin):
    category_id = serializers.IntegerField(required=False, min_value=1)


class EquipmentProductModelOptionsQuerySerializer(OptionsQueryMixin):
    manufacturer_id = serializers.IntegerField(required=False, min_value=1)
    type_id = serializers.IntegerField(required=False, min_value=1)


class ResourceGroupOptionsQuerySerializer(OptionsQueryMixin):
    department_id = serializers.IntegerField(required=False, min_value=1)


class EquipmentOptionsQuerySerializer(OptionsQueryMixin):
    """Filter parameters for Equipment options (ADR 002)."""

    category_id = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Parent filter. Large Equipment selectors require q or at least one declared parent filter.",
    )
    kind_id = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Parent filter. Large Equipment selectors require q or at least one declared parent filter.",
    )
    type_id = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Parent filter. Large Equipment selectors require q or at least one declared parent filter.",
    )
    manufacturer_id = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Parent filter. Large Equipment selectors require q or at least one declared parent filter.",
    )
    lifecycle_status = serializers.CharField(required=False)
    assigned = serializers.BooleanField(required=False, allow_null=True, default=None)
    assignable = serializers.BooleanField(required=False, allow_null=True, default=None)


class CategoryOptionsQuerySerializer(OptionsQueryMixin):
    """Filter parameters for category Equipment options (ADR 002)."""

    kind_id = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Parent filter. Large Equipment selectors require q or at least one declared parent filter.",
    )
    type_id = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Parent filter. Large Equipment selectors require q or at least one declared parent filter.",
    )
    manufacturer_id = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Parent filter. Large Equipment selectors require q or at least one declared parent filter.",
    )
    lifecycle_status = serializers.CharField(required=False)
    assigned = serializers.BooleanField(required=False, allow_null=True, default=None)
    assignable = serializers.BooleanField(required=False, allow_null=True, default=None)
