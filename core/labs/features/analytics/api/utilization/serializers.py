"""Existing utilization contracts."""

from rest_framework import serializers


class LabEfficiencySerializer(serializers.Serializer):
    name = serializers.CharField()
    lab_name = serializers.CharField()
    computer_name = serializers.CharField()
    efficiency = serializers.FloatField()
    duration = serializers.FloatField()
    booking = serializers.IntegerField()


class ProjectUsageSerializer(serializers.Serializer):
    project_name = serializers.CharField()
    usage = serializers.FloatField()


class UserLabUsageSerializer(serializers.Serializer):
    remote_user = serializers.CharField()
    usage = serializers.FloatField()
    remote_user_displayname = serializers.CharField(required=False)


class UserBookingEfficiencySerializer(serializers.Serializer):
    remote_user = serializers.CharField()
    efficiency = serializers.FloatField()
    remote_user_displayname = serializers.CharField(required=False)


class LabUsageTimeframeSerializer(serializers.Serializer):
    timeslot = serializers.CharField()
    usage = serializers.FloatField()


class DateRangeAnalysisQuerySerializer(serializers.Serializer):
    from_date_time = serializers.CharField(required=True)
    to_date_time = serializers.CharField(required=True)

    order = serializers.CharField(required=False, default="desc")
    top = serializers.IntegerField(required=False, min_value=1)


class TimeframeQuerySerializer(serializers.Serializer):
    from_date_time = serializers.CharField(required=True)
    to_date_time = serializers.CharField(required=True)

