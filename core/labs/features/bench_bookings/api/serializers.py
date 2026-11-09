"""Explicit bench booking transport fields; all writes go through commands."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api.options import OptionsQueryMixin
from core.common.api.pagination import PageNumberQuerySerializer
from core.common.api.temporal_query import TemporalBoundField, TemporalRangeQueryMixin
from core.labs.features.base.serializers import (
    AppModelSerializer,
    ChoiceReferenceSerializer,
    NamedReferenceSerializer,
    ResourceOwnerSerializer,
    UIDNamedReferenceSerializer,
    to_choice_reference,
)
from core.labs.models import BenchBooking, BookingStatus, LabProject


class BenchBookingCreateSerializer(serializers.Serializer):
    bench_id = serializers.IntegerField(min_value=1)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    reason = serializers.CharField(allow_blank=False, trim_whitespace=True)
    project_id = serializers.IntegerField(min_value=1)


class BenchBookingUpdateSerializer(serializers.Serializer):
    """Partial update payload; the command enforces which fields may change in each state."""

    bench_id = serializers.IntegerField(min_value=1, required=False)
    starts_at = serializers.DateTimeField(required=False)
    ends_at = serializers.DateTimeField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True)
    project_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    status = serializers.CharField(read_only=True)


class BenchBookingCancelActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="Cancelled by user")


class BenchBookingRejectActionSerializer(serializers.Serializer):
    reason = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        max_length=500,
    )


class BenchBookingSerializer(AppModelSerializer):
    creator = ResourceOwnerSerializer(read_only=True, allow_null=True)
    bench = UIDNamedReferenceSerializer(read_only=True)
    project = NamedReferenceSerializer(read_only=True, allow_null=True)
    status = serializers.SerializerMethodField(read_only=True)
    approval_status = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = BenchBooking
        fields = (
            "id",
            "booking_code",
            "creator",
            "bench",
            "starts_at",
            "ends_at",
            "status",
            "approval_status",
            "project",
            "reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_status(self, obj) -> dict[str, str] | None:
        return to_choice_reference(getattr(obj, "status", None), BookingStatus.choices)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_approval_status(self, obj) -> dict[str, str] | None:
        return to_choice_reference(getattr(obj, "approval_status", None))


class BenchBookingListQuerySerializer(TemporalRangeQueryMixin, PageNumberQuerySerializer):
    """Allowlisted list filters and ordering, including strict calendar-window bounds."""

    temporal_range_fields = ("starts_at_after", "starts_at_before")

    view_side = serializers.ChoiceField(choices=("my_booking", "booking_calendar"), required=False)
    creator = serializers.CharField(required=False)
    creator_id = serializers.IntegerField(required=False, min_value=1)
    bench_id = serializers.IntegerField(required=False, min_value=1)
    project_id = serializers.IntegerField(required=False, min_value=1)
    status = serializers.CharField(required=False)
    approval_status = serializers.CharField(required=False)
    booking_code = serializers.CharField(required=False)
    q = serializers.CharField(required=False)
    search = serializers.CharField(required=False)
    ordering = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=False,
        help_text=(
            "Comma-separated ordering fields: starts_at, ends_at, created_at, id; prefix with '-' for descending. "
            "Defaults to -starts_at,-id. An id tie-breaker is added when omitted."
        ),
    )
    starts_at_after = TemporalBoundField(
        required=False,
        help_text=(
            "Inclusive lower bound. Accepts strict YYYY-MM-DD in Django TIME_ZONE or an offset-aware "
            "RFC3339 datetime (YYYY-MM-DDTHH:MM:SS[.fraction](Z|±HH:MM))."
        ),
    )
    starts_at_before = TemporalBoundField(
        required=False,
        help_text=(
            "Exclusive upper bound. Accepts strict YYYY-MM-DD in Django TIME_ZONE or an offset-aware "
            "RFC3339 datetime (YYYY-MM-DDTHH:MM:SS[.fraction](Z|±HH:MM)). A date-only value is midnight "
            "at the start of that date; to include November 2–8, use starts_at_after=2026-11-02 and "
            "starts_at_before=2026-11-09."
        ),
    )

    def to_internal_value(self, data):
        """Reject duplicate singleton keys before QueryDict's last-value coercion."""
        if hasattr(data, "getlist"):
            duplicate_keys = [key for key in data if len(data.getlist(key)) > 1]
            if duplicate_keys:
                raise serializers.ValidationError(
                    {
                        key: serializers.ErrorDetail("This parameter must not be repeated.", code="invalid_query")
                        for key in duplicate_keys
                    }
                )
        return super().to_internal_value(data)

    def validate_ordering(self, value):
        allowed = {"starts_at", "ends_at", "created_at", "id"}
        fields = value.split(",")
        normalized = [field[1:] if field.startswith("-") else field for field in fields]
        if any(not field or field != field.strip() or field not in allowed for field in normalized) or len(
            set(normalized)
        ) != len(normalized):
            raise serializers.ValidationError(
                "Use unique comma-separated fields from starts_at, ends_at, created_at, id; "
                "prefix a field with '-' for descending.",
                code="invalid_query",
            )
        return fields


class LabProjectQuerySerializer(PageNumberQuerySerializer):
    search = serializers.CharField(required=False, allow_blank=False, max_length=255)
    # default=None: query strings are HTML input, where an absent boolean would otherwise become False.
    active = serializers.BooleanField(required=False, allow_null=True, default=None)


class LabProjectOptionsQuerySerializer(OptionsQueryMixin):
    active_on = serializers.DateField(required=False, help_text="Date within project starts_on and ends_on.")


class LabProjectSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="project_name", read_only=True)

    class Meta:
        model = LabProject
        fields = ("id", "name", "code", "active", "starts_on", "ends_on")
        read_only_fields = fields
        ref_name = "LabProject"
