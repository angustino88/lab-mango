"""Signed gateway intake of telemetry readings (docs/proposals/environment-telemetry.md §7.1)."""

from typing import Any

from django.utils.cache import patch_vary_headers
from drf_api_contracts import OperationContract, ResponseContract
from rest_framework import serializers

from core.agents.api.authentication import IsAuthenticatedAgent
from core.agents.api.observation_authentication import ObservationSignatureAuthentication
from core.common.api.command_views import CommandAPIView
from core.common.api.strict_json import StrictObjectJSONParser
from core.common.domain.errors import BadRequest
from core.labs.features.telemetry.public import IngestOperation, IngestReading, ingest_samples


class TelemetryReadingSerializer(serializers.Serializer):
    channel_id = serializers.IntegerField(min_value=1)
    value = serializers.DecimalField(max_digits=14, decimal_places=4, required=False, allow_null=True, default=None)
    status = serializers.ChoiceField(choices=("ok", "no_response", "error"), required=False, default="ok")
    profile_version = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs["status"] == "ok" and attrs["value"] is None:
            raise serializers.ValidationError({"value": "A reading with status ok needs a value."})
        if attrs["status"] != "ok" and attrs["value"] is not None:
            raise serializers.ValidationError({"value": "Send no value when the channel did not answer."})
        return attrs


class TelemetrySampleSerializer(serializers.Serializer):
    device_uid = serializers.CharField(max_length=64)
    sample_id = serializers.UUIDField(help_text="One per source poll cycle; persisted before the first send.")
    observed_at = serializers.DateTimeField()
    config_version = serializers.IntegerField(min_value=0, required=False)
    readings = TelemetryReadingSerializer(many=True, allow_empty=False)

    def validate_readings(self, value):
        if len(value) > 200:
            raise serializers.ValidationError("Send at most 200 readings per operation.")
        return value


class TelemetryOperationSerializer(serializers.Serializer):
    def get_fields(self):
        # "data" is the bulk envelope key (BLK-1); declared here because it shadows Serializer.data.
        fields = super().get_fields()
        fields["data"] = TelemetrySampleSerializer()
        return fields


class TelemetryBulkSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=("partial",))
    operations = TelemetryOperationSerializer(many=True, allow_empty=False)

    def validate_operations(self, value):
        if len(value) > 500:
            raise serializers.ValidationError("Send at most 500 operations per batch.")
        return value


class TelemetryOperationErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    reading = serializers.IntegerField(required=False, help_text="Index of the rejected reading in the operation.")


class TelemetryOperationResultSerializer(serializers.Serializer):
    # Plain code for gateway software (proposal §7.1), not an operator-facing {value, label} choice.
    status = serializers.CharField(help_text="accepted, duplicate, partially_accepted or rejected.")

    def get_fields(self):
        # Declared here because "errors" shadows Serializer.errors.
        fields = super().get_fields()
        fields["errors"] = TelemetryOperationErrorSerializer(many=True)
        return fields


class TelemetryIngestResultSerializer(serializers.Serializer):
    results = TelemetryOperationResultSerializer(many=True)
    config_version = serializers.IntegerField(help_text="Re-pull the configuration when this is newer.")


class AgentTelemetrySamplesAPIView(CommandAPIView):
    """Readings from a gateway's sources. Each operation is one source's poll cycle; readings are judged one
    by one and attributed through the channel's binding, never through ids in the body. Replays are safe:
    an already stored `sample_id` reports `duplicate`."""

    authentication_classes = [ObservationSignatureAuthentication]
    permission_classes: Any = [IsAuthenticatedAgent]
    parser_classes = [StrictObjectJSONParser]
    schema_tags = ("Agents",)
    post_contract = OperationContract(
        request=TelemetryBulkSerializer,
        success=ResponseContract.success("AgentTelemetryIngest", TelemetryIngestResultSerializer),
        bad_request=ResponseContract.problem(400),
        unauthorized=ResponseContract.problem(401),
        forbidden=ResponseContract.problem(403),
        conflict=ResponseContract.problem(409),
        payload_too_large=ResponseContract.problem(413),
        validation_failed=ResponseContract.problem(422),
        rate_limited=ResponseContract.problem(429),
    )

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        patch_vary_headers(response, ("Accept", "Accept-Language"))
        return response

    def handle_post(self, request):
        if request.query_params:
            raise BadRequest("This endpoint accepts no query parameters.", code="invalid_query")
        serializer, error = self.validate_request()
        if error is not None:
            return error
        assert serializer is not None
        operations = [
            IngestOperation(
                device_uid=item["data"]["device_uid"],
                sample_id=item["data"]["sample_id"],
                observed_at=item["data"]["observed_at"],
                readings=tuple(
                    IngestReading(channel_id=reading["channel_id"], value=reading["value"], status=reading["status"])
                    for reading in item["data"]["readings"]
                ),
            )
            for item in serializer.validated_data["operations"]
        ]
        equipment_id = request.user.identity.equipment_id
        return self._execute(lambda: ingest_samples(gateway_equipment_id=equipment_id, operations=operations))
