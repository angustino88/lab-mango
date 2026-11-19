"""Wire shapes for the session log list."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api.pagination import PageNumberQuerySerializer
from core.common.api.search import SearchQueryMixin
from core.common.api.summary_serializers import UserReferenceSerializer, choice_field, embedded_resource
from core.labs.features.base.serializers import NamedReferenceSerializer, UIDNamedReferenceSerializer
from core.labs.features.lab_sessions.queries import SESSION_LOG_ORDERINGS
from core.labs.models import BookingStatus
from core.labs.models.session.lab_session import SessionAccessType

MAX_RANGE_DAYS = 366


class SessionLogListQuerySerializer(SearchQueryMixin, PageNumberQuerySerializer):
    """Filters for the session list. The date range is required and at most a year long."""

    start_date = serializers.DateField(help_text="First login day, inclusive (server time zone).")
    end_date = serializers.DateField(help_text="Last login day, inclusive (server time zone).")
    bench_id = serializers.IntegerField(required=False, min_value=1)
    computer_id = serializers.IntegerField(required=False, min_value=1)
    user_id = serializers.IntegerField(required=False, min_value=1)
    access_type = serializers.ChoiceField(choices=SessionAccessType.choices, required=False)
    ordering = serializers.ChoiceField(
        choices=sorted(SESSION_LOG_ORDERINGS),
        required=False,
        help_text="Default -login_time (newest first). The row id always breaks ties.",
    )

    class Meta:
        ref_name = "SessionLogListQuery"

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        start, end = attrs["start_date"], attrs["end_date"]
        if end < start:
            raise serializers.ValidationError({"end_date": "The end date must not be before the start date."})
        if (end - start).days >= MAX_RANGE_DAYS:
            raise serializers.ValidationError({"end_date": f"The range may cover at most {MAX_RANGE_DAYS} days."})
        return attrs


@embedded_resource
class SessionLogBookingSerializer(serializers.Serializer):
    """The verified booking a session ran under: its schedule and project, to compare with the session."""

    id = serializers.IntegerField(read_only=True)
    booking_code = serializers.CharField(read_only=True)
    starts_at = serializers.DateTimeField(read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)
    status = choice_field(BookingStatus.choices)
    project = NamedReferenceSerializer(read_only=True, allow_null=True)

    class Meta:
        ref_name = "SessionLogBooking"


class SessionLogItemSerializer(serializers.Serializer):
    """One completed remote session as pushed by the agent, with the links derived from it."""

    id = serializers.IntegerField(read_only=True)
    login_at = serializers.DateTimeField(source="login_time", read_only=True)
    logout_at = serializers.DateTimeField(source="logout_time", read_only=True)
    duration_minutes = serializers.SerializerMethodField(help_text="Logout minus login, in minutes.")
    active_minutes = serializers.SerializerMethodField(help_text="Time the user was active, in minutes.")
    computer = UIDNamedReferenceSerializer(source="computing_equipment", read_only=True, allow_null=True)
    host_name = serializers.CharField(read_only=True, allow_null=True)
    bench = UIDNamedReferenceSerializer(read_only=True, allow_null=True)
    remote_user = serializers.CharField(read_only=True, allow_null=True)
    remote_user_display_name = serializers.CharField(read_only=True, allow_null=True)
    user = UserReferenceSerializer(read_only=True, allow_null=True)
    access_type = choice_field(SessionAccessType.choices, allow_null=True)
    booking_code = serializers.CharField(read_only=True, allow_null=True)
    booking = SessionLogBookingSerializer(
        read_only=True,
        allow_null=True,
        help_text="The verified booking (access type booked); null otherwise.",
    )

    class Meta:
        ref_name = "SessionLogItem"

    @extend_schema_field(serializers.FloatField(allow_null=True))
    def get_duration_minutes(self, obj) -> float | None:
        duration = obj.duration
        return round(duration.total_seconds() / 60, 1) if duration is not None else None

    @extend_schema_field(serializers.FloatField(allow_null=True))
    def get_active_minutes(self, obj) -> float | None:
        seconds = obj.active_duration_seconds
        return round(seconds / 60, 1) if seconds is not None else None


__all__ = ["MAX_RANGE_DAYS", "SessionLogItemSerializer", "SessionLogListQuerySerializer"]
