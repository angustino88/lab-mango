"""Existing insight request and response contracts."""

from rest_framework import serializers


class InsightRangeQuerySerializer(serializers.Serializer):
    """Strict ISO-8601 datetime window for the insight endpoints. Unknown keys are rejected by the view."""

    from_date_time = serializers.DateTimeField(required=True)
    to_date_time = serializers.DateTimeField(required=True)

    def validate(self, attrs):
        if attrs["to_date_time"] <= attrs["from_date_time"]:
            raise serializers.ValidationError("to_date_time must be after from_date_time.")
        return attrs


class CountTrendMetricSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    previous_count = serializers.IntegerField()
    trend_percent = serializers.IntegerField()


class ActiveBenchesMetricSerializer(serializers.Serializer):
    count = serializers.IntegerField()


class DashboardSummarySerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField()
    period_start = serializers.DateTimeField()
    period_end = serializers.DateTimeField()
    bookings = CountTrendMetricSerializer()
    facility_visits = CountTrendMetricSerializer()
    active_benches = ActiveBenchesMetricSerializer()


class BookedVsUsedBenchSerializer(serializers.Serializer):
    bench_id = serializers.IntegerField()
    bench_name = serializers.CharField()
    booked_hours = serializers.FloatField()


class BookedVsUsedSerializer(serializers.Serializer):
    period_start = serializers.DateTimeField()
    period_end = serializers.DateTimeField()
    total_booked_hours = serializers.FloatField()
    total_used_hours = serializers.FloatField()
    used_to_booked_ratio = serializers.FloatField(allow_null=True)
    official_working_hours = serializers.FloatField()
    benches = BookedVsUsedBenchSerializer(many=True)


class EquipmentAvailabilityItemSerializer(serializers.Serializer):
    equipment_id = serializers.IntegerField()
    equipment_name = serializers.CharField()
    uptime_percent = serializers.FloatField()
    unavailable_hours = serializers.FloatField()
    outage_count = serializers.IntegerField()
    current_status = serializers.CharField()


class EquipmentAvailabilitySerializer(serializers.Serializer):
    period_start = serializers.DateTimeField()
    period_end = serializers.DateTimeField()
    equipment_count = serializers.IntegerField()
    average_uptime_percent = serializers.FloatField(allow_null=True)
    items = EquipmentAvailabilityItemSerializer(many=True)
