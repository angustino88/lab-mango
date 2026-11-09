"""Existing count and facility-visit contracts."""

from rest_framework import serializers


class AnalyticsCountTrendSerializer(serializers.Serializer):
    """Aggregate count and week-over-week trend."""

    count = serializers.IntegerField()
    trend = serializers.FloatField()


class AnalyticsAggregatedLogSerializer(serializers.Serializer):
    """Bucket-aggregated historical metrics row."""

    date = serializers.CharField(required=False)
    year = serializers.IntegerField(required=False)
    week = serializers.IntegerField(required=False)
    month = serializers.IntegerField(required=False)
    quarter = serializers.IntegerField(required=False)
    count = serializers.IntegerField()


class UnitQuerySerializer(serializers.Serializer):
    unit = serializers.ChoiceField(choices=["day", "week", "month", "quarter", "year"], required=False)


class LabVisitLogCreateSerializer(serializers.Serializer):
    """Input payload for creating a laboratory visit record."""

    facility_identifier = serializers.CharField(required=False, allow_blank=True, default="")
    external_reference = serializers.CharField(required=False, allow_blank=True, default="")


class LabVisitLogResponseSerializer(serializers.Serializer):
    """Response payload for recorded laboratory visits."""

    id = serializers.IntegerField(required=False)
    facility_identifier = serializers.CharField(required=False, allow_blank=True)
    occurred_at = serializers.DateTimeField(required=False)
