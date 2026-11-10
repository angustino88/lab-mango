"""Equipment category serializer bases and write-field allowlists."""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from core.labs.features.base.serializers import ResourceWriteSerializerMixin
from core.labs.models.resource.base.resource import ResourceGroup

from .serializers import (
    EquipmentKindSerializer,
    EquipmentManufacturerSerializer,
    EquipmentProductModelSerializer,
    EquipmentTypeSerializer,
)

EQUIPMENT_WRITE_FIELDS = (
    "kind",
    "type",
    "manufacturer",
    "product_model",
    "sku",
    "name",
    "serial_number",
    "log_label",
    "details",
    "metadata",
    "replacement_date",
    "owner",
    "department",
    "group",
    "firmware_version",
    "power_draw_w",
    "weight_kg",
    "warranty_until",
    "calibration_required",
)


class EquipmentWriteSerializer(ResourceWriteSerializerMixin, serializers.ModelSerializer):
    """Validate related references before model save, including partial updates."""

    def get_fields(self):
        fields = super().get_fields()
        model = self.Meta.model
        for field_name in tuple(fields):
            model_field = model._meta.get_field(field_name)
            if not model_field.is_relation:
                continue
            input_name = f"{field_name}_ids" if model_field.many_to_many else f"{field_name}_id"
            field = fields.pop(field_name)
            field.source = field_name
            fields[input_name] = field
        return fields

    def validate(self, attrs):
        attrs = super().validate(attrs)

        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: "Unknown or read-only field." for key in sorted(unknown)})

        def value(name):
            return attrs.get(name, getattr(self.instance, name, None) if self.instance else None)

        kind = value("kind")
        equipment_type = value("type")
        manufacturer = value("manufacturer")
        product_model = value("product_model")
        errors = {}
        expected_category = self.Meta.model.EQUIPMENT_CATEGORY_KEY
        if kind and expected_category != "equipment" and kind.category.effective_key != expected_category:
            errors["kind"] = "The equipment kind must belong to the selected category."
        if kind and (not kind.active or not kind.category.active):
            errors["kind"] = "Select an active equipment kind and category."
        if equipment_type and kind and equipment_type.kind_id != kind.pk:
            errors["type"] = "The equipment type must belong to the selected kind."
        if product_model and (not manufacturer or product_model.manufacturer_id != manufacturer.pk):
            errors["product_model"] = "The product model must belong to the selected manufacturer."
        for name, reference in (
            ("type", equipment_type),
            ("manufacturer", manufacturer),
            ("product_model", product_model),
        ):
            if reference and not reference.active:
                errors[name] = "Select an active reference."
        owner = value("owner")
        if owner and not owner.is_active:
            errors["owner"] = "Select an active owner."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class ResourceGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResourceGroup
        fields = ("id", "name")
        read_only_fields = fields


class EquipmentOwnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = get_user_model()
        fields = ("id", "username")
        read_only_fields = fields


class EquipmentFormReferenceSerializer(serializers.Serializer):
    kinds = EquipmentKindSerializer(many=True, read_only=True)
    types = EquipmentTypeSerializer(many=True, read_only=True)
    manufacturers = EquipmentManufacturerSerializer(many=True, read_only=True)
    product_models = EquipmentProductModelSerializer(many=True, read_only=True)
    groups = ResourceGroupSerializer(many=True, read_only=True)
    owners = EquipmentOwnerSerializer(many=True, read_only=True)
