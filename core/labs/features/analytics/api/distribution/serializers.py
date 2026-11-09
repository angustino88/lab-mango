"""Existing distribution contracts."""

from rest_framework import serializers


class BenchGroupSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    bench_group_name = serializers.CharField(required=False)
    total_benches = serializers.IntegerField()
    active_benches = serializers.IntegerField()
    entries = serializers.IntegerField(required=False)


class EquipmentStatusSummarySerializer(serializers.Serializer):
    status = serializers.CharField()
    count = serializers.IntegerField()
    entries = serializers.IntegerField(required=False)
