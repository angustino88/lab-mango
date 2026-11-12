"""Serializers for resource auditing API endpoints."""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from core.common.api import AppModelSerializer
from core.common.api.pagination import PageNumberQuerySerializer
from core.labs.models.auditing.resource_audit import ResourceAudit

User = get_user_model()


class ResourceAuditorSerializer(AppModelSerializer):
    """User summary for audit actor."""

    class Meta:
        model = User
        fields = ("id", "username", "display_name")
        ref_name = "ResourceAuditorUserSummary"


class ResourceAuditItemSerializer(AppModelSerializer):
    """Full detail of a recorded resource audit."""

    auditor = ResourceAuditorSerializer(read_only=True)
    resource_type = serializers.SerializerMethodField()
    resource_id = serializers.SerializerMethodField()
    resource_name = serializers.SerializerMethodField()
    resource_sku = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(source="created", read_only=True)

    class Meta:
        model = ResourceAudit
        fields = (
            "id",
            "resource_type",
            "resource_id",
            "resource_name",
            "resource_sku",
            "auditor",
            "result",
            "remarks",
            "audited_at",
            "created_at",
        )
        ref_name = "ResourceAuditItem"

    def get_resource_type(self, obj: ResourceAudit) -> str:
        if obj.resource_content_type:
            return obj.resource_content_type.model
        return ""

    def get_resource_id(self, obj: ResourceAudit) -> str:
        return obj.resource_object_id

    def get_resource_name(self, obj: ResourceAudit) -> str:
        res = obj.resource
        if res:
            return getattr(res, "name", "") or str(res)
        return ""

    def get_resource_sku(self, obj: ResourceAudit) -> str:
        res = obj.resource
        if res:
            return getattr(res, "sku", "") or getattr(res, "code", "")
        return ""


AUDIT_RESULT_INPUT_CHOICES: list[str] = ["PASS", "FAIL", "NOT_ASSESSED", "OK", "NOK"]


class RecordResourceAuditRequestSerializer(serializers.Serializer):
    """Payload to record an audit on a specific resource."""

    result = serializers.ChoiceField(
        choices=AUDIT_RESULT_INPUT_CHOICES,
        required=True,
    )
    remarks = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=255,
    )
    audited_at = serializers.DateTimeField(required=False, allow_null=True)

    class Meta:
        ref_name = "RecordResourceAuditRequest"


class UpdateResourceAuditRequestSerializer(serializers.Serializer):
    """Payload to update an existing audit record."""

    result = serializers.ChoiceField(
        choices=AUDIT_RESULT_INPUT_CHOICES,
        required=False,
    )
    remarks = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
    )
    audited_at = serializers.DateTimeField(required=False, allow_null=True)

    class Meta:
        ref_name = "UpdateResourceAuditRequest"


class AuditBySkuRequestSerializer(serializers.Serializer):
    """Payload to create or update audit for a resource resolved by its SKU."""

    audit_id = serializers.CharField(required=False, allow_blank=True, max_length=255)
    auditor = serializers.CharField(required=False, allow_blank=True, max_length=255)
    audit_status = serializers.ChoiceField(
        choices=AUDIT_RESULT_INPUT_CHOICES,
        required=False,
    )
    result = serializers.ChoiceField(
        choices=AUDIT_RESULT_INPUT_CHOICES,
        required=False,
    )
    remarks = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=255,
    )
    audited_at = serializers.DateTimeField(required=False, allow_null=True)

    class Meta:
        ref_name = "AuditBySkuRequest"


class ResourceAuditListQuerySerializer(PageNumberQuerySerializer):
    """Query filters for audits listing."""

    resource_type = serializers.CharField(required=False)
    result = serializers.ChoiceField(
        choices=AUDIT_RESULT_INPUT_CHOICES,
        required=False,
    )
    auditor_id = serializers.IntegerField(required=False)
    search = serializers.CharField(required=False)

    class Meta:
        ref_name = "ResourceAuditListQuery"
