from django.utils import timezone
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from core.common.api.options import OptionsQueryMixin
from core.common.api.summary_serializers import StatusSummarySerializer
from core.labs.features.base.serializers import (
    AppModelSerializer,
    ChoiceReferenceSerializer,
    MoneySerializer,
    NamedReferenceSerializer,
    ResourceOwnerSerializer,
    ResourceWriteSerializerMixin,
    UIDNamedReferenceSerializer,
    to_choice_reference,
    to_money,
)
from core.labs.features.equipment.api.capabilities import EQUIPMENT_CAPABILITIES
from core.labs.models import (
    Equipment,
    EquipmentCategory,
    EquipmentCondition,
    EquipmentDisplayStatus,
    EquipmentKind,
    EquipmentLifecycleState,
    EquipmentLoan,
    EquipmentManufacturer,
    EquipmentProductModel,
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


class EquipmentLoanSerializer(serializers.Serializer):
    """Who holds a unit and until when. ``overdue`` is computed: open and past ``due_at``."""

    id = serializers.IntegerField(read_only=True)
    borrower = ResourceOwnerSerializer(read_only=True)
    booking_id = serializers.IntegerField(read_only=True, allow_null=True)
    handed_over_at = serializers.DateTimeField(read_only=True)
    due_at = serializers.DateTimeField(read_only=True)
    overdue = serializers.SerializerMethodField()
    condition_out = serializers.CharField(read_only=True)
    returned_at = serializers.DateTimeField(read_only=True, allow_null=True)
    condition_in = serializers.CharField(read_only=True)
    close_reason = serializers.CharField(read_only=True, allow_null=True)

    class Meta:
        ref_name = "EquipmentLoan"

    def get_overdue(self, obj) -> bool:
        return obj.returned_at is None and obj.due_at < timezone.now()


class EquipmentHandOverSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    borrower_id = serializers.IntegerField(min_value=1)
    due_at = serializers.DateTimeField(help_text="When the equipment must be back; in the future.")
    condition_out = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class EquipmentReturnSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    """Close the loan; optionally record the condition and where the equipment now is."""

    condition_in = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    condition = serializers.ChoiceField(choices=EquipmentCondition.choices, required=False, allow_null=True, default=None)
    bench_id = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    station_id = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    room_id = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    location_note = serializers.CharField(max_length=LOCATION_NOTE_MAX_LENGTH, required=False, allow_blank=True, default="")


class EquipmentExtendLoanSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    due_at = serializers.DateTimeField()


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
    display_status = serializers.SerializerMethodField(read_only=True)
    lifecycle_state = serializers.SerializerMethodField(read_only=True)
    condition = serializers.SerializerMethodField(read_only=True)
    acquisition_price = serializers.SerializerMethodField(read_only=True)
    placement = serializers.SerializerMethodField(read_only=True)
    loan = serializers.SerializerMethodField(read_only=True)

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
            "loan",
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
            "display_status",
            "lifecycle_state",
            "condition",
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

    @extend_schema_field(EquipmentLoanSerializer(allow_null=True))
    def get_loan(self, obj) -> dict | None:
        """Open loan from the projection's prefetch; ``null`` when nobody holds the unit."""
        loans = getattr(obj, "active_loans", None)
        if loans is None:  # instance not built by an equipment projection
            loans = list(EquipmentLoan.objects.filter(equipment_id=obj.pk, returned_at__isnull=True).select_related("borrower"))
        return EquipmentLoanSerializer(loans[0], context=self.context).data if loans else None

    @extend_schema_field(ChoiceReferenceSerializer(allow_null=True))
    def get_display_status(self, obj) -> dict[str, str] | None:
        """Computed in SQL by the equipment projections; never stored."""
        return to_choice_reference(getattr(obj, "display_status", None), EquipmentDisplayStatus.choices)

    @extend_schema_field(ChoiceReferenceSerializer())
    def get_lifecycle_state(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.lifecycle_state, EquipmentLifecycleState.choices)

    @extend_schema_field(ChoiceReferenceSerializer())
    def get_condition(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.condition, EquipmentCondition.choices)


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
            "lifecycle_state",
        )
        extra_kwargs = {"sku": {"validators": []}}


class EquipmentAssignmentSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    bench_id = serializers.IntegerField(min_value=1)
    role = serializers.CharField(max_length=64, required=False, default="default")
    position = serializers.IntegerField(min_value=0, required=False, default=0)


class EquipmentChangeConditionSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    condition = serializers.ChoiceField(choices=EquipmentCondition.choices)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class EquipmentChangeLifecycleSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    lifecycle_state = serializers.ChoiceField(choices=EquipmentLifecycleState.choices)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    receiving_organisation = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        help_text="Required when lifecycle_state is transferred_out.",
    )
    transfer_date = serializers.DateField(
        required=False, allow_null=True, default=None, help_text="Defaults to today for transferred_out."
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
    lifecycle_state = serializers.ChoiceField(choices=EquipmentLifecycleState.choices, required=False)
    status = serializers.ChoiceField(
        choices=EquipmentDisplayStatus.choices, required=False, help_text="Filters the computed display_status."
    )
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
    lifecycle_state = serializers.ChoiceField(choices=EquipmentLifecycleState.choices, required=False)
    status = serializers.ChoiceField(
        choices=EquipmentDisplayStatus.choices, required=False, help_text="Filters the computed display_status."
    )
    assigned = serializers.BooleanField(required=False, allow_null=True, default=None)
    assignable = serializers.BooleanField(required=False, allow_null=True, default=None)
