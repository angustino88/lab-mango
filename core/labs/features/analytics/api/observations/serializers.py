"""Existing count and facility-visit contracts."""

from django.utils import timezone
from rest_framework import serializers

from ...public import DEFAULT_DAILY_WINDOW_DAYS, MAX_DAILY_WINDOW_DAYS, resolve_daily_window


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
    """Optional bucketing and local-calendar-day range for the count endpoints (QRY-5)."""

    unit = serializers.ChoiceField(choices=["day", "week", "month", "quarter", "year"], required=False)
    date_after = serializers.DateField(
        required=False,
        help_text=(
            "First local day to include (YYYY-MM-DD, inclusive). Requires `unit`. For `unit=day` the "
            f"default is {DEFAULT_DAILY_WINDOW_DAYS} days before `date_before`."
        ),
    )
    date_before = serializers.DateField(
        required=False,
        help_text=(
            "Local day to stop before (YYYY-MM-DD, exclusive). Requires `unit`. For `unit=day` the "
            f"default is tomorrow, so today is included; a range covers at most {MAX_DAILY_WINDOW_DAYS} days."
        ),
    )

    def validate(self, attrs):
        date_after, date_before = attrs.get("date_after"), attrs.get("date_before")
        if "unit" not in attrs:
            if date_after is not None or date_before is not None:
                raise serializers.ValidationError({"unit": ["This field is required when a date range is given."]})
            return attrs
        if attrs["unit"] == "day":
            try:
                resolve_daily_window(date_after, date_before, today=timezone.localdate())
            except ValueError as exc:
                raise serializers.ValidationError({"date_before": [str(exc)]}) from exc
        elif date_after is not None and date_before is not None and date_after >= date_before:
            raise serializers.ValidationError({"date_before": ["date_after must be before date_before."]})
        return attrs


class LabVisitLogCreateSerializer(serializers.Serializer):
    """Input payload for creating a laboratory visit record."""

    facility_identifier = serializers.CharField(required=False, allow_blank=True, default="")
    external_reference = serializers.CharField(required=False, allow_blank=True, default="")


class LabVisitLogResponseSerializer(serializers.Serializer):
    """Response payload for recorded laboratory visits."""

    id = serializers.IntegerField(required=False)
    facility_identifier = serializers.CharField(required=False, allow_blank=True)
    occurred_at = serializers.DateTimeField(required=False)
