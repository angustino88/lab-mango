"""Strict, bounded snapshots; the computer is always credential-derived."""

import re
import unicodedata
from datetime import timezone as datetime_timezone

from drf_spectacular.extensions import OpenApiSerializerExtension
from rest_framework import serializers

from core.common.api.summary_serializers import choice_field
from core.labs.features.monitoring.contracts import DeviceObservation


class ObservationTextField(serializers.CharField):
    def __init__(self, **kwargs):
        super().__init__(trim_whitespace=False, **kwargs)

    def to_internal_value(self, data):
        if isinstance(data, str):
            if any(unicodedata.category(character) == "Cc" for character in data):
                raise serializers.ValidationError("Control characters are not supported.", code="invalid_format")
            data = unicodedata.normalize("NFC", data)
            if not data.strip():
                if not self.allow_blank:
                    raise serializers.ValidationError("This field must not be blank.", code="blank")
                data = ""
        return super().to_internal_value(data)


class ObservationUUIDField(serializers.UUIDField):
    def to_internal_value(self, data):
        if not isinstance(data, str) or not re.fullmatch(
            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", data
        ):
            raise serializers.ValidationError("Use a hyphenated UUID.", code="invalid_format")
        return super().to_internal_value(data)


class StrictObservationSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError({key: "Unknown or read-only field." for key in sorted(unknown)})
        return super().to_internal_value(data)


class DeviceObservationSerializer(StrictObservationSerializer):
    observation_key = ObservationTextField(max_length=255)
    interface_name = ObservationTextField(max_length=255)
    state = serializers.ChoiceField(choices=(("connected", "Connected"), ("disconnected", "Disconnected")))
    name = ObservationTextField(max_length=255, allow_blank=True, required=False, default="")
    serial_number = ObservationTextField(max_length=255, allow_blank=True, required=False, default="")


class ObservationDateTimeField(serializers.DateTimeField):
    def to_internal_value(self, data):
        try:
            return super().to_internal_value(data)
        except serializers.ValidationError:
            raise serializers.ValidationError(
                "Use RFC 3339 with an explicit timezone.", code="invalid_format"
            ) from None


class DeviceObservationListSerializer(serializers.ListSerializer):
    def to_internal_value(self, data):
        if isinstance(data, list) and len(data) > 200:
            raise serializers.ValidationError("At most 200 devices are supported.", code="max_items")
        return super().to_internal_value(data)


class DeviceObservationReportSerializer(StrictObservationSerializer):
    generation_key = ObservationUUIDField()
    collector_key = serializers.RegexField(r"^[a-z][a-z0-9_-]{0,31}$", max_length=32)
    sequence = serializers.IntegerField(min_value=1, max_value=9007199254740991)
    collected_at = ObservationDateTimeField()
    is_complete = serializers.BooleanField()
    devices: serializers.ListSerializer = DeviceObservationListSerializer(
        child=DeviceObservationSerializer(), max_length=200, allow_empty=True
    )

    def validate_collected_at(self, value):
        raw = self.initial_data.get("collected_at", "")
        if not isinstance(raw, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", raw
        ):
            raise serializers.ValidationError("Use RFC 3339 with an explicit timezone.", code="invalid_format")
        return value

    def validate_devices(self, value):
        keys = [row["observation_key"] for row in value]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError("Observation keys must be unique.")
        return tuple(DeviceObservation(**row) for row in value)


class ObservationAcknowledgmentSerializer(serializers.Serializer):
    batch_key = serializers.UUIDField()
    sequence = serializers.IntegerField()
    disposition = choice_field((("applied", "Applied"), ("stale", "Stale")))
    received_at = serializers.DateTimeField(default_timezone=datetime_timezone.utc, format="%Y-%m-%dT%H:%M:%S.%fZ")


class MonitoringPolicySerializer(serializers.Serializer):
    generation_key = ObservationUUIDField()
    max_devices = serializers.IntegerField()
    max_body_bytes = serializers.IntegerField()
    freshness_seconds = serializers.IntegerField()
    interface_names = serializers.ListField(child=serializers.CharField())


class ClosedObservationSchema(OpenApiSerializerExtension):
    target_class = "core.agents.api.observation_serializers.StrictObservationSerializer"
    match_subclasses = True

    def map_serializer(self, auto_schema, direction):
        schema = auto_schema._map_serializer(self.target, direction, bypass_extensions=True)
        schema["additionalProperties"] = False
        return schema
