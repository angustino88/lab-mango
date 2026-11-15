"""Serializers for the leaderboard feature domain."""
from __future__ import annotations

from drf_api_contracts import PaginatedResponseEnvelopeSerializer, ResponseEnvelopeSerializer
from rest_framework import serializers


class DashboardLabItemSerializer(serializers.Serializer):
    """Item representation in dashboard laboratory listing."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    sku = serializers.CharField(required=False)
    status = serializers.CharField(required=False, default="available")


class DashboardUnpaginatedResponseSerializer(ResponseEnvelopeSerializer):
    """Unpaginated envelope for dashboard laboratory listings."""

    data = DashboardLabItemSerializer(many=True)


class DashboardPaginatedResponseSerializer(PaginatedResponseEnvelopeSerializer):
    """Paginated envelope for dashboard laboratory listings."""

    data = DashboardLabItemSerializer(many=True)


class LeaderboardPersonaSerializer(serializers.Serializer):
    """Ranking metrics and performance breakdown for individual users."""

    id = serializers.IntegerField()
    username = serializers.CharField()
    display_name = serializers.CharField(allow_blank=True, default="")
    avatar = serializers.CharField(allow_null=True, required=False)
    points = serializers.IntegerField()
    wfo_rate = serializers.FloatField(required=False, default=0.0)
    wfh_rate = serializers.FloatField(required=False, default=0.0)
    late_rate = serializers.FloatField(required=False, default=0.0)
    usage_efficiency = serializers.FloatField(required=False, default=0.0)
    booking_compliance = serializers.FloatField(required=False, default=0.0)
    last_remote_at = serializers.DateTimeField(source="last_remote", allow_null=True, required=False)
    labs_accessed = serializers.IntegerField(required=False, default=0)
    total_bookings = serializers.IntegerField(required=False, default=0)
    total_sessions = serializers.IntegerField()
    total_usage_minutes = serializers.FloatField(required=False, default=0.0)
    avg_session_minutes = serializers.FloatField(required=False, default=0.0)
    longest_session_minutes = serializers.FloatField(required=False, default=0.0)
    top_projects = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class LeaderboardLabSerializer(serializers.Serializer):
    """Utilization rankings for laboratories and benches."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    points = serializers.IntegerField()
    total_sessions = serializers.IntegerField()
    active_users = serializers.IntegerField(required=False, default=0)
    last_remote_at = serializers.DateTimeField(source="last_remote", allow_null=True, required=False)
    downtime_minutes = serializers.FloatField(required=False, default=0.0)
    top_projects = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class LabProfileSerializer(serializers.Serializer):
    """Laboratory bench profile metrics and usage statistics."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    sku = serializers.CharField(required=False)
    total_sessions = serializers.IntegerField()
    active_users = serializers.IntegerField()
    top_projects = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class UserProfileSerializer(serializers.Serializer):
    """User profile overview and ranking metrics."""

    id = serializers.IntegerField()
    username = serializers.CharField()
    display_name = serializers.CharField(allow_blank=True, default="")
    total_sessions = serializers.IntegerField()
    points = serializers.IntegerField()
    top_projects = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class WeeklyUsageSlotSerializer(serializers.Serializer):
    """Weekly utilization heatmap slot."""

    day = serializers.IntegerField()
    hour = serializers.IntegerField()
    usage = serializers.FloatField()


class DashboardSummaryDataSerializer(serializers.Serializer):
    """High-level asset count and status distribution summary."""

    total = serializers.IntegerField()
    status = serializers.DictField(child=serializers.IntegerField())


# --- Query Serializers ---

class LeaderboardDateRangeQuerySerializer(serializers.Serializer):
    start_date = serializers.CharField(required=False)
    end_date = serializers.CharField(required=False)


class LeaderboardExportQuerySerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["persona", "lab"], default="persona")
    start_date = serializers.CharField(required=False)
    end_date = serializers.CharField(required=False)


__all__ = [
    "DashboardSummaryDataSerializer",
    "LabProfileSerializer",
    "LeaderboardDateRangeQuerySerializer",
    "LeaderboardExportQuerySerializer",
    "LeaderboardLabSerializer",
    "LeaderboardPersonaSerializer",
    "UserProfileSerializer",
    "WeeklyUsageSlotSerializer",
]
