"""Shared serializers for current Labs resource models."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from rest_framework import serializers

from core.common.api import AppModelSerializer
from core.common.api.api_views import RESOURCE_FIELD_IMMUTABLE
from core.labs.models.auditing.resource_audit import ResourceAudit
from core.labs.models.resource.base.resource import Department
from core.labs.models.resource.base.service_record import ResourceServiceRecord

User = get_user_model()


class ResourceOwnerSerializer(AppModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "display_name")
        ref_name = "LabsResourceOwner"


class DepartmentSerializer(AppModelSerializer):
    class Meta:
        model = Department
        fields = ("id", "name", "description", "active")
        ref_name = "LabsDepartment"


class ResourceServiceRecordSerializer(AppModelSerializer):
    performed_by = ResourceOwnerSerializer(read_only=True, allow_null=True)
    certificate_url = serializers.FileField(source="certificate", read_only=True, allow_null=True)

    class Meta:
        model = ResourceServiceRecord
        fields = (
            "id",
            "kind",
            "performed_at",
            "next_due_at",
            "performed_by",
            "vendor",
            "result",
            "certificate_no",
            "certificate_url",
            "notes",
            "created",
        )
        ref_name = "LabsResourceServiceRecord"


class ResourceAuditSerializer(AppModelSerializer):
    auditor = ResourceOwnerSerializer(read_only=True)

    class Meta:
        model = ResourceAudit
        fields = ("id", "auditor", "result", "remarks", "audited_at")
        ref_name = "LabsResourceAudit"


class NamedReferenceSerializer(serializers.Serializer):
    """Compact `{id, name}` object representation of a related entity."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)

    class Meta:
        ref_name = "LabsNamedReference"


class UIDNamedReferenceSerializer(serializers.Serializer):
    """Compact `{id, uid, name}` object representation when target defines a UUID."""

    id = serializers.IntegerField(read_only=True)
    uid = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)

    class Meta:
        ref_name = "LabsUIDNamedReference"


class ChoiceReferenceSerializer(serializers.Serializer):
    """Standard `{value, label}` representation for enum and lifecycle choices."""

    value = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True)

    class Meta:
        ref_name = "LabsChoiceReference"


class MoneySerializer(serializers.Serializer):
    """Standard `{amount, currency}` representation for monetary values."""

    amount = serializers.CharField(read_only=True)
    currency = serializers.CharField(read_only=True)

    class Meta:
        ref_name = "LabsMoney"


class Coordinate3DSerializer(serializers.Serializer):
    """Standard `{x, y, z}` representation for 3D coordinates."""

    x = serializers.FloatField(read_only=True)
    y = serializers.FloatField(read_only=True)
    z = serializers.FloatField(read_only=True)

    class Meta:
        ref_name = "LabsCoordinate3D"


def to_choice_reference(value: str | None, choices=None) -> dict[str, str] | None:
    if value is None:
        return None
    choice_dict = dict(choices) if choices else {}
    label = str(choice_dict.get(value, value.replace("_", " ").title()))
    return {"value": str(value), "label": label}


def to_money(amount: Any, currency: Any) -> dict[str, Any] | None:
    if amount is None or currency is None:
        return None
    decimal_amount = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    return {"amount": format(decimal_amount, "f"), "currency": currency}


class ResourceWriteSerializerMixin:
    """Reject unsupported keys and return a stable error when SKU is supplied on update."""

    immutable_update_fields = ("sku",)

    def to_internal_value(self, data):
        unknown = set()
        if isinstance(data, Mapping):
            immutable = set(data) & set(self.immutable_update_fields)
            is_update = self.instance is not None or self.context.get("resource_update", False)
            if is_update and immutable:
                names = ", ".join(sorted(immutable))
                raise serializers.ValidationError(
                    {
                        "code": [RESOURCE_FIELD_IMMUTABLE],
                        "detail": [f"{names} cannot be changed after resource creation."],
                    }
                )
            if is_update:
                data = {key: value for key, value in data.items() if key not in self.immutable_update_fields}
            unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({field: "Unknown or read-only field." for field in sorted(unknown)})
        return super().to_internal_value(data)


__all__ = (
    "AppModelSerializer",
    "ChoiceReferenceSerializer",
    "Coordinate3DSerializer",
    "DepartmentSerializer",
    "MoneySerializer",
    "NamedReferenceSerializer",
    "ResourceAuditSerializer",
    "ResourceOwnerSerializer",
    "ResourceServiceRecordSerializer",
    "ResourceWriteSerializerMixin",
    "UIDNamedReferenceSerializer",
    "to_choice_reference",
    "to_money",
)
