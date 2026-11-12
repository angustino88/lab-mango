from typing import Any

from drf_spectacular.utils import extend_schema_field
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
from core.labs.models import License, LicenseAgreement, LicenseStatus, LicenseStatusRecord
from core.labs.models.resource.license.license import (
    LicenseCategory,
    LicenseProduct,
    LicenseRestriction,
    LicenseType,
    LicenseVendor,
)

from .filters import LICENSE_FILTERS


class LicenseStatusSummarySerializer(StatusSummarySerializer):
    """Recorded state only; expiry and assignment are not recomputed."""


class LicenseCategorySummarySerializer(serializers.Serializer):
    id = serializers.IntegerField(source="category_id_value", allow_null=True)
    name = serializers.CharField(source="category_name", allow_null=True)
    resource_count = serializers.IntegerField(min_value=0)


class LicenseSerializer(AppModelSerializer):
    owner = NamedReferenceSerializer(read_only=True, allow_null=True)
    department = NamedReferenceSerializer(read_only=True, allow_null=True)
    group = NamedReferenceSerializer(read_only=True, allow_null=True)
    product = NamedReferenceSerializer(read_only=True, allow_null=True)
    vendor = NamedReferenceSerializer(read_only=True, allow_null=True)
    type = NamedReferenceSerializer(read_only=True, allow_null=True)
    category = NamedReferenceSerializer(read_only=True, allow_null=True)
    restriction = NamedReferenceSerializer(read_only=True, allow_null=True)
    seats_in_use = serializers.IntegerField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)
    acquisition_price = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = License
        fields = (
            "id",
            "uid",
            "sku",
            "name",
            "owner",
            "department",
            "group",
            "remark",
            "product",
            "vendor",
            "type",
            "category",
            "restriction",
            "seats",
            "seats_in_use",
            "max_version",
            "expiry_date",
            "status",
            "acquisition_price",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(ChoiceReferenceSerializer(allow_null=True))
    def get_status(self, obj) -> dict[str, str] | None:
        raw_status = getattr(obj, "current_status", None)
        if raw_status is None and hasattr(obj, "status"):
            raw_status = obj.status
        return to_choice_reference(raw_status, LicenseStatus.choices)

    @extend_schema_field(MoneySerializer(allow_null=True))
    def get_acquisition_price(self, obj) -> dict[str, Any] | None:
        amount = getattr(obj, "acquisition_price", None)
        currency = getattr(obj, "acquisition_currency", None)
        return to_money(amount, currency)


LicenseListQuerySerializer = LICENSE_FILTERS.serializer("LicenseListQuerySerializer")


class LicenseStatusSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    status = serializers.ChoiceField(choices=LicenseStatus.choices)
    details = serializers.JSONField(required=False, default=dict)


class LicenseStatusRecordSerializer(AppModelSerializer):
    license = NamedReferenceSerializer(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = LicenseStatusRecord
        fields = ("id", "license", "status", "metadata", "created_at")
        read_only_fields = fields

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_status(self, obj) -> dict[str, str] | None:
        return to_choice_reference(getattr(obj, "status", None), LicenseStatus.choices)


class LicenseAssignmentRequestSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    equipment_id = serializers.IntegerField(min_value=1)


class LicenseAssignmentResultSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    equipment = serializers.SerializerMethodField(read_only=True)
    license = serializers.SerializerMethodField(read_only=True)
    assigned_at = serializers.DateTimeField(read_only=True)
    unassigned_at = serializers.DateTimeField(read_only=True, allow_null=True)

    @extend_schema_field(UIDNamedReferenceSerializer)
    def get_equipment(self, obj) -> dict[str, Any]:
        return UIDNamedReferenceSerializer(obj.equipment).data

    @extend_schema_field(UIDNamedReferenceSerializer)
    def get_license(self, obj) -> dict[str, Any]:
        return UIDNamedReferenceSerializer(obj.license).data


class LicenseAgreementSerializer(AppModelSerializer):
    license = NamedReferenceSerializer(read_only=True)
    price = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = LicenseAgreement
        fields = (
            "id",
            "license",
            "price",
            "billing_period",
            "valid_from",
            "valid_until",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(MoneySerializer)
    def get_price(self, obj) -> dict[str, Any] | None:
        return to_money(getattr(obj, "price", None), getattr(obj, "currency", None))


class LicenseAgreementWriteSerializer(ResourceWriteSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = LicenseAgreement
        fields = (
            "price",
            "currency",
            "billing_period",
            "valid_from",
            "valid_until",
        )

    def validate(self, attrs):
        valid_until = attrs.get("valid_until")
        valid_from = attrs.get("valid_from")
        if valid_until is not None and valid_from is not None and valid_until < valid_from:
            raise serializers.ValidationError({"valid_until": "Must be on or after valid_from."})
        return attrs


class LicenseVendorSerializer(AppModelSerializer):
    class Meta:
        model = LicenseVendor
        fields = ("id", "name", "created_at", "updated_at")
        ref_name = "LicenseVendorCatalogItem"


class LicenseProductSerializer(AppModelSerializer):
    vendor = LicenseVendorSerializer(read_only=True)
    vendor_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = LicenseProduct
        fields = ("id", "name", "vendor", "vendor_id", "created_at", "updated_at")
        ref_name = "LicenseProductCatalogItem"


class LicenseTypeSerializer(AppModelSerializer):
    class Meta:
        model = LicenseType
        fields = ("id", "name", "created_at", "updated_at")
        ref_name = "LicenseTypeCatalogItem"


class LicenseCategorySerializer(AppModelSerializer):
    class Meta:
        model = LicenseCategory
        fields = ("id", "name", "created_at", "updated_at")
        ref_name = "LicenseCategoryCatalogItem"


class LicenseRestrictionSerializer(AppModelSerializer):
    class Meta:
        model = LicenseRestriction
        fields = ("id", "name", "created_at", "updated_at")
        ref_name = "LicenseRestrictionCatalogItem"


class LicenseProductOptionsQuerySerializer(OptionsQueryMixin):
    vendor_id = serializers.IntegerField(required=False, min_value=1)


__all__ = (
    "LicenseAgreementSerializer",
    "LicenseAgreementWriteSerializer",
    "LicenseAssignmentRequestSerializer",
    "LicenseAssignmentResultSerializer",
    "LicenseCategorySerializer",
    "LicenseListQuerySerializer",
    "LicenseProductOptionsQuerySerializer",
    "LicenseProductSerializer",
    "LicenseRestrictionSerializer",
    "LicenseSerializer",
    "LicenseStatusRecordSerializer",
    "LicenseStatusSerializer",
    "LicenseTypeSerializer",
    "LicenseVendorSerializer",
)
