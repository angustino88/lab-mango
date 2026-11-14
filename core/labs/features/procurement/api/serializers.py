from django.contrib.contenttypes.models import ContentType
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from core.common.api import AppModelSerializer
from core.common.api.summary_serializers import ChoiceSerializer, choice_field, to_choice
from core.labs.models import Purchase, PurchaseItem, PurchaseItemResource, PurchasePriority, PurchaseTransaction
from core.labs.models.procurement.purchase import PURCHASE_RESOURCE_MODELS

RESOURCE_KIND_MODELS = {
    model: model
    for model in ("bench", "equipment", "license", "station")
    if ("labs", model) in PURCHASE_RESOURCE_MODELS
}


_MONEY_SCHEMA = {
    "type": "object",
    "properties": {
        "amount": {"type": "string", "pattern": r"^-?[0-9]+(\.[0-9]+)?$"},
        "currency": {"type": "string", "description": "Purchase currency code."},
    },
    "required": ["amount", "currency"],
    "additionalProperties": False,
}


class PurchaseItemSerializer(AppModelSerializer):
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=2, write_only=True)
    purpose = serializers.CharField(max_length=2_000, required=False, allow_blank=False, allow_null=True)
    priority_id = serializers.IntegerField(min_value=1, required=False, allow_null=True, write_only=True)
    unit = serializers.CharField(max_length=32, required=False, allow_blank=False, allow_null=True)

    class Meta:
        model = PurchaseItem
        fields = (
            "id",
            "description",
            "quantity",
            "unit_price",
            "notes",
            "purpose",
            "priority_id",
            "unit",
            "created_at",
        )
        read_only_fields = ("id", "created_at")
        extra_kwargs = {"unit_price": {"write_only": True}}

    def validate(self, attrs):
        return _validate_priority_ids(attrs)


def _validate_priority_ids(attrs):
    priority_id = attrs.get("priority_id")
    if priority_id is not None and not PurchasePriority.objects.filter(pk=priority_id, is_active=True).exists():
        raise serializers.ValidationError({"priority_id": "Select an active purchase priority."})
    return attrs


class PurchaseItemReadSerializer(AppModelSerializer):
    purchase = serializers.SerializerMethodField()
    unit_price = serializers.SerializerMethodField()
    purpose = serializers.CharField(read_only=True)
    unit = serializers.CharField(read_only=True)
    line_value = serializers.SerializerMethodField()
    priority = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseItem
        fields = (
            "id", "purchase", "description", "quantity", "unit", "unit_price", "line_value",
            "priority", "purpose", "notes", "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.DictField(child=serializers.JSONField()))
    def get_purchase(self, obj) -> dict[str, int | str]:
        return {"id": obj.purchase_id, "name": obj.purchase.purchase_order_number or str(obj.purchase_id)}

    @extend_schema_field(_MONEY_SCHEMA)
    def get_unit_price(self, obj) -> dict[str, str]:
        return {"amount": format(obj.unit_price, "f"), "currency": obj.purchase.currency}

    @extend_schema_field(_MONEY_SCHEMA)
    def get_line_value(self, obj) -> dict[str, str]:
        return {"amount": format(obj.quantity * obj.unit_price, ".2f"), "currency": obj.purchase.currency}

    def get_priority(self, obj) -> dict[str, int | str] | None:
        if obj.priority is None:
            return None
        return {"id": obj.priority_id, "code": obj.priority.code, "name": obj.priority.name}


class PurchasePriorityOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    code = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class PurchasePriorityQuerySerializer(serializers.Serializer):
    include_inactive = serializers.ChoiceField(choices=("true", "false"), required=False, default="false")


class PurchaseDraftHeaderInputSerializer(serializers.Serializer):
    supplier = serializers.CharField(max_length=255, required=False, allow_blank=False)
    purchase_date = serializers.DateField(required=False)
    purchase_order_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    currency = serializers.CharField(min_length=3, max_length=3, required=False)
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False)
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True, allow_null=False)


class DraftLineInputSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=255, allow_blank=False)
    quantity = serializers.IntegerField(min_value=1, max_value=1_000_000)
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0)
    notes = serializers.CharField(max_length=2_000, required=False, allow_blank=True)
    purpose = serializers.CharField(max_length=2_000, required=False, allow_blank=False, allow_null=True)
    priority_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    unit = serializers.CharField(max_length=32, required=False, allow_blank=False, allow_null=True)

    def validate(self, attrs):
        return _validate_priority_ids(attrs)


class DraftLinePatchInputSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=255, required=False, allow_blank=False)
    quantity = serializers.IntegerField(min_value=1, max_value=1_000_000, required=False)
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False)
    notes = serializers.CharField(max_length=2_000, required=False, allow_blank=True)
    purpose = serializers.CharField(max_length=2_000, required=False, allow_blank=False, allow_null=True)
    priority_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    unit = serializers.CharField(max_length=32, required=False, allow_blank=False, allow_null=True)

    def validate(self, attrs):
        return _validate_priority_ids(attrs)


class PurchaseDetailSerializer(serializers.ModelSerializer):
    lines_total = serializers.SerializerMethodField()
    unpriced_line_count = serializers.SerializerMethodField()
    item_count = serializers.IntegerField(read_only=True)
    total_amount = serializers.SerializerMethodField()
    status = choice_field(Purchase._meta.get_field("status").choices)
    created_at = serializers.DateTimeField(source="created", read_only=True)
    updated_at = serializers.DateTimeField(source="modified", read_only=True)

    class Meta:
        model = Purchase
        fields = (
            "id", "supplier", "purchase_order_number", "purchase_date", "currency", "total_amount",
            "status", "notes", "version", "item_count", "lines_total", "unpriced_line_count",
            "created_at", "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(_MONEY_SCHEMA)
    def get_total_amount(self, obj) -> dict[str, str]:
        return {"amount": format(obj.total_amount, ".2f"), "currency": obj.currency}

    @extend_schema_field(_MONEY_SCHEMA)
    def get_lines_total(self, obj) -> dict[str, str]:
        return {"amount": format(obj.items_total, ".2f"), "currency": obj.currency}

    def get_unpriced_line_count(self, obj) -> int:
        return obj.items.filter(unit_price=0).count()


class PurchaseDraftHeaderOutputSerializer(serializers.ModelSerializer):
    total_amount = serializers.SerializerMethodField()
    status = choice_field(Purchase._meta.get_field("status").choices)

    class Meta:
        model = Purchase
        fields = ("id", "supplier", "purchase_order_number", "purchase_date", "currency", "total_amount", "status", "notes", "version")
        read_only_fields = fields

    @extend_schema_field(_MONEY_SCHEMA)
    def get_total_amount(self, obj) -> dict[str, str]:
        return {"amount": format(obj.total_amount, ".2f"), "currency": obj.currency}


class PurchaseItemDetailSerializer(PurchaseItemReadSerializer):
    version = serializers.IntegerField(read_only=True)

    class Meta(PurchaseItemReadSerializer.Meta):
        fields = (*PurchaseItemReadSerializer.Meta.fields, "version")
        read_only_fields = fields


class PurchaseSerializer(AppModelSerializer):
    items = PurchaseItemSerializer(
        many=True,
        required=False,
        write_only=True,
    )
    status = serializers.SerializerMethodField(read_only=True)
    total = serializers.SerializerMethodField(read_only=True)
    item_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Purchase
        fields = (
            "id",
            "supplier",
            "purchase_order_number",
            "purchase_date",
            "currency",
            "status",
            "total_amount",
            "total",
            "item_count",
            "notes",
            "created_at",
            "updated_at",
            "items",
        )
        read_only_fields = ("id", "created_at")

    @extend_schema_field(serializers.DictField(child=serializers.CharField()))
    def get_status(self, obj) -> dict[str, str]:
        return {"value": obj.status, "label": obj.get_status_display()}

    @extend_schema_field(_MONEY_SCHEMA)
    def get_total(self, obj) -> dict[str, str]:
        return {"amount": format(obj.total_amount, "f"), "currency": obj.currency}

    def get_item_count(self, obj) -> int:
        if hasattr(obj, "item_count"):
            return obj.item_count
        if hasattr(obj, "_prefetched_objects_cache") and "items" in obj._prefetched_objects_cache:
            return len(obj.items.all())
        return obj.items.count()


@extend_schema_serializer(
    component_name="PurchaseItemResourceCreate",
    description=(
        "Supply resource_kind, legacy resource_type_id, or both. At least one is required. "
        "If both are supplied, they must identify the same resource kind."
    ),
)
class PurchaseItemResourceCreateSerializer(AppModelSerializer):
    resource_kind = serializers.ChoiceField(
        choices=tuple(RESOURCE_KIND_MODELS),
        required=False,
        write_only=True,
        help_text="Stable resource kind. Supply this or legacy resource_type_id; if both are supplied, they must match.",
    )
    resource_type_id = serializers.IntegerField(
        min_value=1,
        required=False,
        write_only=True,
        help_text="Legacy resource type ID.",
    )
    resource_id = serializers.IntegerField(min_value=1)
    acquisition_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=0,
        write_only=True,
    )

    class Meta:
        model = PurchaseItemResource
        fields = ("resource_kind", "resource_type_id", "resource_id", "acquisition_price")

    def validate(self, attrs):
        attrs = super().validate(attrs)
        resource_kind = attrs.get("resource_kind")
        resource_type_id = attrs.get("resource_type_id")
        if resource_kind is None and resource_type_id is None:
            raise serializers.ValidationError({"resource_kind": "Supply either resource_kind or resource_type_id."})

        kind_content_type: ContentType | None = None
        if resource_kind is not None:
            model = RESOURCE_KIND_MODELS[resource_kind]
            if ("labs", model) not in PURCHASE_RESOURCE_MODELS:
                raise serializers.ValidationError({"resource_kind": "Unsupported resource kind."})
            kind_content_type = ContentType.objects.filter(app_label="labs", model=model).first()
            if kind_content_type is None:
                raise serializers.ValidationError({"resource_kind": "Resource kind is unavailable."})

        if resource_type_id is not None:
            legacy_content_type = ContentType.objects.filter(pk=resource_type_id).first()
            if (
                legacy_content_type is None
                or (
                    legacy_content_type.app_label,
                    legacy_content_type.model,
                )
                not in PURCHASE_RESOURCE_MODELS
            ):
                raise serializers.ValidationError({"resource_type_id": "Unsupported resource type."})
            if kind_content_type is not None and legacy_content_type.pk != kind_content_type.pk:
                raise serializers.ValidationError(
                    {"resource_type_id": "Must identify the same resource type as resource_kind."}
                )
            attrs["resource_type_id"] = legacy_content_type.pk
        else:
            if kind_content_type is None:
                raise serializers.ValidationError({"resource_kind": "Resource kind is unavailable."})
            attrs["resource_type_id"] = kind_content_type.pk
        return attrs


class PurchaseItemResourceSerializer(AppModelSerializer):
    purchase_item = serializers.SerializerMethodField(read_only=True)
    resource = serializers.SerializerMethodField(read_only=True)
    resource_kind = serializers.SerializerMethodField(read_only=True)
    acquisition_price = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PurchaseItemResource
        fields = (
            "id",
            "purchase_item",
            "resource",
            "resource_kind",
            "acquisition_price",
            "created_at",
        )
        read_only_fields = fields

    def get_purchase_item(self, obj) -> dict[str, int | str]:
        return {"id": obj.purchase_item_id, "name": obj.purchase_item.description}

    def get_resource(self, obj) -> dict[str, int | str] | None:
        resource = obj.resource
        if resource is None:
            return None
        return {"id": resource.pk, "name": getattr(resource, "name", str(resource))}

    @extend_schema_field(ChoiceSerializer)
    def get_resource_kind(self, obj) -> dict[str, str] | None:
        return to_choice(obj.resource_type.model)

    @extend_schema_field(_MONEY_SCHEMA)
    def get_acquisition_price(self, obj) -> dict[str, str]:
        purchase = obj.purchase_item.purchase
        return {"amount": format(obj.acquisition_price, "f"), "currency": purchase.currency}


class PurchaseTransactionWriteSerializer(serializers.ModelSerializer):
    """Write payload (RW-1). The purchase is taken from the URL, never from the body."""

    class Meta:
        model = PurchaseTransaction
        fields = ("transaction_type", "amount", "settled_at", "reference", "notes")
        extra_kwargs = {
            "transaction_type": {"required": True},
            "amount": {"required": True},
            "settled_at": {"required": True},
        }


class PurchaseTransactionSerializer(AppModelSerializer):
    """Read shape; ``transaction_type`` is ``{value, label}`` (ENU-1)."""

    purchase = serializers.SerializerMethodField(read_only=True)
    transaction_type = choice_field(PurchaseTransaction._meta.get_field("transaction_type").choices)

    class Meta:
        model = PurchaseTransaction
        fields = (
            "id",
            "purchase",
            "transaction_type",
            "amount",
            "settled_at",
            "reference",
            "notes",
            "created_at",
        )
        read_only_fields = fields

    def get_purchase(self, obj) -> dict[str, int | str]:
        return {"id": obj.purchase_id, "name": obj.purchase.purchase_order_number or str(obj.purchase_id)}
