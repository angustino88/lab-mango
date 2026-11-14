"""Existing insight request and response contracts."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.labs.features.base.serializers import NamedReferenceSerializer


class ReportPeriodSerializer(serializers.Serializer):
    """NAM-9 ``period`` group read from the row's ``period_start`` / ``period_end``."""

    starts_at = serializers.DateTimeField(source="period_start")
    ends_at = serializers.DateTimeField(source="period_end")


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
    period = ReportPeriodSerializer(source="*")
    bookings = CountTrendMetricSerializer()
    facility_visits = CountTrendMetricSerializer()
    active_benches = ActiveBenchesMetricSerializer()


class BookedVsUsedBenchSerializer(serializers.Serializer):
    bench = serializers.SerializerMethodField()  # REL-14
    booked_hours = serializers.FloatField()

    @extend_schema_field(NamedReferenceSerializer)
    def get_bench(self, row) -> dict:
        return {"id": row["bench_id"], "name": row["bench_name"]}


class BookedVsUsedSerializer(serializers.Serializer):
    period = ReportPeriodSerializer(source="*")
    total_booked_hours = serializers.FloatField()
    total_used_hours = serializers.FloatField()
    used_to_booked_ratio = serializers.FloatField(allow_null=True)
    official_working_hours = serializers.FloatField()
    benches = BookedVsUsedBenchSerializer(many=True)


class EquipmentAvailabilityItemSerializer(serializers.Serializer):
    equipment = serializers.SerializerMethodField()  # REL-14
    uptime_percent = serializers.FloatField()
    unavailable_hours = serializers.FloatField()
    outage_count = serializers.IntegerField()
    current_status = serializers.CharField()

    @extend_schema_field(NamedReferenceSerializer)
    def get_equipment(self, row) -> dict:
        return {"id": row["equipment_id"], "name": row["equipment_name"]}


class EquipmentAvailabilitySerializer(serializers.Serializer):
    period = ReportPeriodSerializer(source="*")
    equipment_count = serializers.IntegerField()
    average_uptime_percent = serializers.FloatField(allow_null=True)
    items = EquipmentAvailabilityItemSerializer(many=True)
