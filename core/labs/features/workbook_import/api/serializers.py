"""Payload shapes of the workbook import endpoints."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api.summary_serializers import choice_field

from ..contracts import MODE_CHOICES as _MODE_CHOICES
from ..contracts import MODE_CREATE


@extend_schema_field(OpenApiTypes.BINARY)
class _WorkbookFileField(serializers.FileField):
    """Documents the multipart part as binary."""


class WorkbookUploadSerializer(serializers.Serializer):
    file = _WorkbookFileField(help_text="The data workbook (.xlsx), at most 10 MB and 5,000 rows per sheet.")
    mode = serializers.ChoiceField(
        choices=_MODE_CHOICES,
        default=MODE_CREATE,
        required=False,
        help_text="create (default): an existing asset tag is an error. upsert: an existing asset tag updates "
        "that record; blank cells keep stored values; the asset tag never changes.",
    )


class ImportProblemSerializer(serializers.Serializer):
    sheet = serializers.CharField(help_text="Sheet name as in the workbook.")
    row = serializers.IntegerField(allow_null=True, help_text="Excel row number; null for a sheet-level problem.")
    column = serializers.CharField(allow_null=True, help_text="Column name as in the template; null when general.")
    severity = choice_field((("error", "Error"), ("warning", "Warning")))
    code = serializers.CharField(help_text="Stable snake_case problem code.")
    message = serializers.CharField()


class SheetOutcomeSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    rows = serializers.IntegerField(help_text="Non-empty data rows read.")
    created = serializers.IntegerField(help_text="Rows that create a record (or would, for a check).")
    updated = serializers.IntegerField(help_text="Rows that change an existing record (upsert mode only).")
    existing = serializers.IntegerField(
        help_text="Rows that match an existing record and change nothing (reference rows; unchanged rows in upsert)."
    )
    failed = serializers.IntegerField()
    ignored_columns = serializers.ListField(child=serializers.CharField())


class ImportSummarySerializer(serializers.Serializer):
    created = serializers.IntegerField()
    updated = serializers.IntegerField()
    existing = serializers.IntegerField()
    error_count = serializers.IntegerField()
    warning_count = serializers.IntegerField()


class ImportReportSerializer(serializers.Serializer):
    is_dry_run = serializers.BooleanField(source="dry_run", help_text="True for a check: nothing was saved.")
    is_valid = serializers.BooleanField(
        source="valid", help_text="True when the workbook has no errors and can be applied."
    )
    template_version = serializers.CharField(allow_null=True)
    mode = choice_field(_MODE_CHOICES)
    summary = serializers.SerializerMethodField()
    sheets = SheetOutcomeSerializer(many=True)
    problems = ImportProblemSerializer(many=True)
    unknown_sheets = serializers.ListField(child=serializers.CharField(), help_text="Sheets that were not read.")

    @extend_schema_field(ImportSummarySerializer)
    def get_summary(self, report):
        return {
            "created": report.created_count,
            "updated": report.updated_count,
            "existing": report.existing_count,
            "error_count": report.error_count,
            "warning_count": report.warning_count,
        }


__all__ = ["ImportReportSerializer", "WorkbookUploadSerializer"]
