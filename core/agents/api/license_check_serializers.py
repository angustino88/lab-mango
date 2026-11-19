"""Strict, bounded license-check runs; the reporting computer is always credential-derived."""

from rest_framework import serializers

from core.common.api.summary_serializers import choice_field
from core.labs.features.equipment.public import normalize_hardware_id

from .observation_serializers import (
    HARDWARE_ID_KINDS,
    ObservationTextField,
    ObservationUUIDField,
    StrictObservationSerializer,
)

MAX_LICENSES = 500
RUN_STATUSES = (
    ("ok", "OK: the license list is complete"),
    ("not_installed", "Tool, file or key not on this computer"),
    ("failed", "Ran but failed"),
    ("rejected", "The agent refused the configuration"),
)
CARRIER_ID_KINDS = (("vector_device", "Vector device name"),)
CARRIER_TYPES = (
    ("computer", "This computer"),
    ("device", "Hardware mounted to the computer"),
    ("dongle", "License dongle"),
    ("server", "License server"),
    ("equipment", "Unit configured on the check"),
)


class CarrierIdSerializer(StrictObservationSerializer):
    """The carrier as the license tool names it (Vector device name); never a PnP ID."""

    kind = serializers.ChoiceField(choices=CARRIER_ID_KINDS)
    value = ObservationTextField(max_length=512)


class ReportedCarrierSerializer(StrictObservationSerializer):
    type = serializers.ChoiceField(choices=CARRIER_TYPES)
    hardware_id = CarrierIdSerializer(required=False)
    equipment_uid = ObservationUUIDField(required=False)


class ReportedLicenseSerializer(StrictObservationSerializer):
    observation_key = ObservationTextField(max_length=255)
    vendor = ObservationTextField(max_length=128, required=False, allow_blank=True, default="")
    product_code = ObservationTextField(max_length=128, required=False, allow_blank=True, default="")
    product_name = ObservationTextField(max_length=255)
    license_serial = ObservationTextField(
        max_length=128,
        required=False,
        allow_blank=True,
        default="",
        help_text="The tool's license serial or ID; matched to License.serial_number. Never a license key.",
    )
    carrier = ReportedCarrierSerializer()
    expires_at = serializers.DateTimeField(allow_null=True, required=False, default=None)
    final_expires_at = serializers.DateTimeField(allow_null=True, required=False, default=None)
    max_version = ObservationTextField(max_length=64, required=False, allow_blank=True, default="")
    is_reactivatable = serializers.BooleanField(required=False, default=False)


class RunErrorSerializer(StrictObservationSerializer):
    code = ObservationTextField(max_length=64)
    message = ObservationTextField(max_length=512, required=False, allow_blank=True, default="")


class LicenseCheckRunReportSerializer(StrictObservationSerializer):
    revision = serializers.IntegerField(min_value=1)
    sequence = serializers.IntegerField(min_value=0, max_value=2**63 - 1)
    status = serializers.ChoiceField(choices=RUN_STATUSES)
    started_at = serializers.DateTimeField()
    reported_at = serializers.DateTimeField(required=False, help_text="Agent clock; informational.")
    duration_ms = serializers.IntegerField(min_value=0, max_value=3_600_000, required=False, default=0)
    is_complete = serializers.BooleanField()
    error = RunErrorSerializer(required=False)
    licenses = ReportedLicenseSerializer(many=True, max_length=MAX_LICENSES)

    def validate(self, attrs):
        is_ok = attrs["status"] == "ok"
        if attrs["is_complete"] != is_ok:
            raise serializers.ValidationError({"is_complete": "Only an 'ok' run is complete."})
        if not is_ok and attrs["licenses"]:
            raise serializers.ValidationError({"licenses": "Only an 'ok' run lists licenses."})
        for item in attrs["licenses"]:
            hardware_id = item["carrier"].get("hardware_id")
            if hardware_id:
                hardware_id["value"] = normalize_hardware_id(hardware_id["kind"], hardware_id["value"])
        return attrs


class LicenseCheckDefinitionSerializer(serializers.Serializer):
    """One check as the agent parses it (``agent/src/core/licensing/checks.py``)."""

    key = serializers.CharField()
    revision = serializers.IntegerField()
    name = serializers.CharField()
    vendor = serializers.CharField()
    interval_minutes = serializers.IntegerField()
    probe = serializers.JSONField()
    extract = serializers.JSONField()
    carrier = serializers.JSONField()


class AgentLicenseChecksSerializer(serializers.Serializer):
    checks = LicenseCheckDefinitionSerializer(many=True)


class LicenseCheckRunAcknowledgmentSerializer(serializers.Serializer):
    idempotency_key = serializers.UUIDField()
    sequence = serializers.IntegerField()
    result = choice_field(
        (
            ("applied", "Applied"),
            ("recorded", "Recorded; licenses unchanged"),
            ("stale", "Older than a run already received"),
            ("outdated_revision", "The check changed; fetch it again"),
        )
    )
    received_at = serializers.DateTimeField()


__all__ = (
    "HARDWARE_ID_KINDS",
    "AgentLicenseChecksSerializer",
    "LicenseCheckRunAcknowledgmentSerializer",
    "LicenseCheckRunReportSerializer",
)
