"""Serializers for resource auditing API endpoints."""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from core.common.api import AppModelSerializer
from core.common.api.pagination import PageNumberQuerySerializer
from core.labs.features.resource_audit.public import (
    CATALOG_PAGE_SIZE_DEFAULT,
    CATALOG_PAGE_SIZE_MAX,
    CATALOG_RESOURCE_TYPES,
)
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


class AuditCatalogQuerySerializer(serializers.Serializer):
    """Query for the audit catalog: start a sync with ``changed_since``/``page_size``, continue with ``cursor``."""

    changed_since = serializers.DateTimeField(
        required=False,
        help_text="Return only rows created, changed or deleted at or after this time. Omit for a full download.",
    )
    cursor = serializers.CharField(
        required=False,
        max_length=2048,
        help_text="Opaque next_cursor from the previous page. Send it alone; it carries the filter and page size.",
    )
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=CATALOG_PAGE_SIZE_MAX,
        default=CATALOG_PAGE_SIZE_DEFAULT,
    )

    class Meta:
        ref_name = "AuditCatalogQuery"

    def validate(self, attrs):
        if "cursor" in self.initial_data and ({"changed_since", "page_size"} & set(self.initial_data)):
            raise serializers.ValidationError(
                {"cursor": ["Send cursor alone; changed_since and page_size come from the cursor."]}
            )
        return attrs


class AuditCatalogItemSerializer(serializers.Serializer):
    """One auditable resource as the audit tool stores it offline. Never carries license keys."""

    uid = serializers.UUIDField()
    resource_type = serializers.ChoiceField(choices=CATALOG_RESOURCE_TYPES)
    sku = serializers.CharField(allow_blank=True)
    name = serializers.CharField(allow_blank=True)
    serial_number = serializers.CharField(allow_blank=True, help_text="Equipment only; empty for other types.")
    status = serializers.CharField(
        allow_blank=True,
        help_text=(
            "Equipment lifecycle_state, bench lifecycle_status, or the newest status record of a station, room "
            "or license; empty when none exists."
        ),
    )
    condition = serializers.CharField(allow_blank=True, help_text="Equipment only; empty for other types.")
    location = serializers.CharField(
        allow_blank=True,
        help_text="Bench: setup station name. Station: room name. Room: building name. Otherwise empty.",
    )
    expiry_date = serializers.DateTimeField(allow_null=True, help_text="License expiry; null for other types.")
    updated_at = serializers.DateTimeField()
    deleted = serializers.BooleanField(help_text="True when the resource was deleted; remove it from the local copy.")

    class Meta:
        ref_name = "AuditCatalogItem"


class AuditCatalogPaginationSerializer(serializers.Serializer):
    count = serializers.IntegerField(allow_null=True, help_text="Always null: not computed for cursor pages.")
    page_size = serializers.IntegerField(min_value=1)
    next_cursor = serializers.CharField(allow_null=True)
    previous_cursor = serializers.CharField(allow_null=True, help_text="Always null: the catalog pages forward only.")

    class Meta:
        ref_name = "AuditCatalogPagination"


class AuditCatalogMetaSerializer(serializers.Serializer):
    pagination = AuditCatalogPaginationSerializer()
    server_time = serializers.DateTimeField(
        help_text="Time the sync started. Store it and send it as changed_since on the next sync.",
    )

    class Meta:
        ref_name = "AuditCatalogMeta"


class AuditCatalogResponseSerializer(serializers.Serializer):
    """Cursor-paged envelope; reserved keys are declared in get_fields for schema generation."""

    class Meta:
        ref_name = "AuditCatalogResponse"

    def get_fields(self):
        fields = super().get_fields()
        fields["data"] = AuditCatalogItemSerializer(many=True)
        fields["meta"] = AuditCatalogMetaSerializer()
        return fields
