"""Serializers for resource auditing API endpoints."""

from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api import AppModelSerializer
from core.common.api.pagination import PageNumberQuerySerializer
from core.common.api.summary_serializers import ChoiceSerializer, UserReferenceSerializer, choice_field, to_choice
from core.common.api.wire_names import relation_name
from core.labs.features.resource_audit.public import (
    CATALOG_PAGE_SIZE_DEFAULT,
    CATALOG_PAGE_SIZE_MAX,
    CATALOG_RESOURCE_TYPES,
)
from core.labs.models.auditing.resource_audit import ResourceAudit

User = get_user_model()


class AuditedResourceSerializer(serializers.Serializer):
    """REL-13 polymorphic relation to the audited resource."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    type = serializers.ChoiceField(choices=CATALOG_RESOURCE_TYPES, read_only=True)


class ResourceAuditItemSerializer(AppModelSerializer):
    """Full detail of a recorded resource audit."""

    resource = serializers.SerializerMethodField()
    auditor = UserReferenceSerializer(read_only=True)
    result = choice_field(ResourceAudit._meta.get_field("result").choices)
    created_at = serializers.DateTimeField(source="created", read_only=True)

    class Meta:
        model = ResourceAudit
        fields = (
            "id",
            "resource",
            "auditor",
            "result",
            "remarks",
            "audited_at",
            "created_at",
        )
        ref_name = "ResourceAuditItem"

    @extend_schema_field(AuditedResourceSerializer)
    def get_resource(self, obj: ResourceAudit) -> dict:
        resource_type = obj.resource_content_type.model if obj.resource_content_type else ""
        target = obj.resource
        name = relation_name(target) if target is not None else f"Deleted {resource_type}"  # REL-12
        return {"id": int(obj.resource_object_id), "name": name, "type": resource_type}


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
    resource_type = serializers.SerializerMethodField()
    sku = serializers.CharField(allow_blank=True)
    name = serializers.CharField(allow_blank=True)
    serial_number = serializers.CharField(allow_blank=True, help_text="Equipment only; empty for other types.")
    status = serializers.CharField(
        allow_blank=True,
        help_text=(
            "Equipment lifecycle_state; bench, station or room lifecycle_status; or the newest status record "
            "of a license; empty when none exists."
        ),
    )
    condition = serializers.CharField(
        allow_blank=True,
        help_text="Computed from downtime (operational, in_maintenance, out_of_service); empty for licenses.",
    )
    location = serializers.CharField(
        allow_blank=True,
        help_text="Bench: setup station name. Station: room name. Room: building name. Otherwise empty.",
    )
    expires_at = serializers.DateTimeField(
        source="expiry_date", allow_null=True, help_text="License expiry; null for other types."
    )
    updated_at = serializers.DateTimeField()
    is_deleted = serializers.BooleanField(
        source="deleted", help_text="True when the resource was deleted; remove it from the local copy."
    )

    class Meta:
        ref_name = "AuditCatalogItem"

    @extend_schema_field(ChoiceSerializer)
    def get_resource_type(self, row) -> dict[str, str] | None:
        return to_choice(row["resource_type"], [(value, value.capitalize()) for value in CATALOG_RESOURCE_TYPES])


class AuditCatalogPaginationSerializer(serializers.Serializer):
    count = serializers.IntegerField(allow_null=True, help_text="Always null: not computed for cursor pages.")
    page_size = serializers.IntegerField(min_value=1)
    next_cursor = serializers.CharField(allow_null=True)
    previous_cursor = serializers.CharField(allow_null=True, help_text="Always null: the catalog pages forward only.")

    class Meta:
        ref_name = "AuditCatalogPagination"


class AuditCatalogMetaSerializer(serializers.Serializer):
    pagination = AuditCatalogPaginationSerializer()
    sync_started_at = serializers.DateTimeField(
        source="server_time",
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
