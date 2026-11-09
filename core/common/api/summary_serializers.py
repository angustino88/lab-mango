"""Reusable wire shapes, without domain choices or model imports."""

from rest_framework import serializers


class SummaryStatusSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class SummaryStatusCountSerializer(serializers.Serializer):
    status = SummaryStatusSerializer()
    resource_count = serializers.IntegerField(min_value=0)


class StatusSummarySerializer(serializers.Serializer):
    total_count = serializers.IntegerField(min_value=0)
    unknown_status_count = serializers.IntegerField(
        min_value=0,
        help_text="Resources without a recorded status or with an unrecognized status.",
    )
    statuses = SummaryStatusCountSerializer(
        many=True,
        help_text="All code-defined states, including zero counts. Values are extensible.",
    )


