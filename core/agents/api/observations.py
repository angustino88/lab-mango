"""Signed agent intake for one atomic collector snapshot resource."""

import hashlib
import json
import re
from typing import Any
from uuid import UUID

from django.utils.cache import patch_vary_headers
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from rest_framework.response import Response

from core.agents.api.authentication import IsAuthenticatedAgent
from core.agents.api.observation_authentication import ObservationSignatureAuthentication
from core.agents.api.observation_serializers import (
    DeviceObservationReportSerializer,
    MonitoringPolicySerializer,
    ObservationAcknowledgmentSerializer,
)
from core.agents.application import ReportDeviceObservationsInput, report_device_observations
from core.agents.queries import monitoring_policy
from core.common.api.command_views import CommandAPIView
from core.common.api.strict_json import StrictObjectJSONParser
from core.common.domain.errors import BadRequest
from core.labs.features.monitoring.contracts import DeviceObservationInput


class AgentMonitoringPolicyAPIView(CommandAPIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = (
            "no-store" if request.method == "POST" or response.status_code >= 400 else "private, no-cache"
        )
        patch_vary_headers(response, ("Accept", "Accept-Language"))
        return response

    authentication_classes = [ObservationSignatureAuthentication]
    permission_classes: Any = [IsAuthenticatedAgent]
    parser_classes = [StrictObjectJSONParser]
    schema_tags = ("Agents",)
    get_contract = OperationContract(
        success=ResponseContract.success("AgentMonitoringPolicy", MonitoringPolicySerializer),
        not_modified=ResponseContract.documented(304, OpenApiResponse(response=None, description="Policy unchanged")),
        unauthorized=ResponseContract.problem(401),
        rate_limited=ResponseContract.problem(429),
        bad_request=ResponseContract.problem(400),
    )

    def handle_get(self, request):
        if request.body:
            raise BadRequest("GET does not accept a body.", code="unexpected_body")
        if request.query_params:
            raise BadRequest("This endpoint accepts no query parameters.", code="invalid_query")
        response = self._execute(lambda: monitoring_policy(request.user.identity))
        etag = '"' + hashlib.sha256(json.dumps(response.data, sort_keys=True, default=str).encode()).hexdigest() + '"'
        supplied = request.headers.get("If-None-Match", "")
        if any(candidate.strip().removeprefix("W/") in {etag, "*"} for candidate in supplied.split(",")):
            response = Response(status=304)
        response["ETag"] = etag
        return response


class AgentDeviceObservationsAPIView(CommandAPIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = (
            "no-store" if request.method == "POST" or response.status_code >= 400 else "private, no-cache"
        )
        patch_vary_headers(response, ("Accept", "Accept-Language"))
        return response

    authentication_classes = [ObservationSignatureAuthentication]
    permission_classes: Any = [IsAuthenticatedAgent]
    parser_classes = [StrictObjectJSONParser]
    schema_tags = ("Agents",)
    post_contract = OperationContract(
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Durable UUID batch key; reuse on retry with the same content.",
            )
        ],
        request=DeviceObservationReportSerializer,
        success=ResponseContract.success("AgentDeviceObservations", ObservationAcknowledgmentSerializer),
        bad_request=ResponseContract.problem(400),
        unauthorized=ResponseContract.problem(401),
        rate_limited=ResponseContract.problem(429),
        conflict=ResponseContract.problem(409),
        validation_failed=ResponseContract.problem(422),
        payload_too_large=ResponseContract.problem(413),
    )

    def handle_post(self, request):
        if request.query_params:
            raise BadRequest("This endpoint accepts no query parameters.", code="invalid_query")
        # Authentication already signed raw bytes, so this rejects oversized input
        # before JSON decoding or nested validation in this workflow.
        if len(request.body) > 262144:
            return self.respond_problem(
                "payload_too_large", code="payload_too_large", detail="Snapshot exceeds 256 KiB."
            )
        request.data  # Parse structural/media errors before idempotency validation.
        raw_key = request.headers.get("Idempotency-Key")
        if raw_key is None:
            raise BadRequest("An Idempotency-Key header is required.", code="idempotency_key_required")
        try:
            if len(raw_key) > 64:
                raise ValueError
            batch_key = UUID(raw_key)
            if str(batch_key) != raw_key.lower():
                raise ValueError
        except (ValueError, TypeError):
            raise BadRequest("Idempotency-Key must be a UUID.", code="invalid_idempotency_key") from None
        serializer, error = self.validate_request()
        if error is not None:
            details = error.data["error"]["details"][:100]
            for detail in details:
                if isinstance(detail.get("field"), str):
                    detail["field"] = re.sub(r"\.(\d+)(?=\.|$)", r"[\1]", detail["field"])
            error.data["error"]["details"] = details
            return error
        assert serializer is not None
        identity = request.user.identity
        command = ReportDeviceObservationsInput(
            identity,
            DeviceObservationInput(
                computer_id=identity.equipment_id,
                agent_key=str(identity.agent_uid),
                batch_key=batch_key,
                **serializer.validated_data,
            ),
        )
        result = report_device_observations(command, actor=identity)
        response = self.respond(result)
        if result.is_replayed:
            response["Idempotency-Replayed"] = "true"
        return response
