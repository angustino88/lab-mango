"""Signed agent routes for license checks: fetch the configured checks, report one run."""

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
from core.agents.api.license_check_serializers import (
    AgentLicenseChecksSerializer,
    LicenseCheckRunAcknowledgmentSerializer,
    LicenseCheckRunReportSerializer,
)
from core.agents.api.observation_authentication import ObservationSignatureAuthentication
from core.agents.application import ReportLicenseCheckRunInput, report_license_check
from core.common.api.command_views import CommandAPIView
from core.common.api.strict_json import StrictObjectJSONParser
from core.common.domain.errors import BadRequest
from core.labs.features.license_checks.public import (
    LicenseCheckRunInput,
    ReportedLicense,
    agent_check_definitions,
)

MAX_BODY = 262144


class _AgentLicenseCheckAPIView(CommandAPIView):
    authentication_classes = [ObservationSignatureAuthentication]
    permission_classes: Any = [IsAuthenticatedAgent]
    parser_classes = [StrictObjectJSONParser]
    schema_tags = ("Agents",)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = (
            "no-store" if request.method == "POST" or response.status_code >= 400 else "private, no-cache"
        )
        patch_vary_headers(response, ("Accept", "Accept-Language"))
        return response


class AgentLicenseChecksAPIView(_AgentLicenseCheckAPIView):
    """The enabled checks that target this computer; strong ETag, 304 when unchanged."""

    get_contract = OperationContract(
        success=ResponseContract.success("AgentLicenseChecks", AgentLicenseChecksSerializer),
        not_modified=ResponseContract.documented(304, OpenApiResponse(response=None, description="Checks unchanged")),
        unauthorized=ResponseContract.problem(401),
        rate_limited=ResponseContract.problem(429),
        bad_request=ResponseContract.problem(400),
    )

    def handle_get(self, request):
        if request.body:
            raise BadRequest("GET does not accept a body.", code="unexpected_body")
        if request.query_params:
            raise BadRequest("This endpoint accepts no query parameters.", code="invalid_query")
        identity = request.user.identity
        response = self._execute(lambda: {"checks": agent_check_definitions(computing_id=identity.equipment_id)})
        etag = '"' + hashlib.sha256(json.dumps(response.data, sort_keys=True, default=str).encode()).hexdigest() + '"'
        supplied = request.headers.get("If-None-Match", "")
        if any(candidate.strip().removeprefix("W/") in {etag, "*"} for candidate in supplied.split(",")):
            response = Response(status=304)
        response["ETag"] = etag
        return response


def _reported(item: dict) -> ReportedLicense:
    carrier = item["carrier"]
    hardware_id = carrier.get("hardware_id") or {}
    return ReportedLicense(
        observation_key=item["observation_key"],
        product_name=item["product_name"],
        carrier_type=carrier["type"],
        vendor=item["vendor"],
        product_code=item["product_code"],
        license_serial=item["license_serial"].strip(),
        carrier_hardware_kind=hardware_id.get("kind", ""),
        carrier_hardware_value=hardware_id.get("value", ""),
        carrier_equipment_uid=str(carrier.get("equipment_uid") or ""),
        expires_at=item["expires_at"],
        final_expires_at=item["final_expires_at"],
        max_version=item["max_version"],
        is_reactivatable=item["is_reactivatable"],
    )


class AgentLicenseCheckReportAPIView(_AgentLicenseCheckAPIView):
    """One run of one check. Exact retries with the same Idempotency-Key are acknowledged again."""

    post_contract = OperationContract(
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Durable UUID run key; reuse on retry with the same content.",
            )
        ],
        request=LicenseCheckRunReportSerializer,
        success=ResponseContract.success("AgentLicenseCheckReport", LicenseCheckRunAcknowledgmentSerializer),
        bad_request=ResponseContract.problem(400),
        unauthorized=ResponseContract.problem(401),
        not_found=ResponseContract.problem(404),
        rate_limited=ResponseContract.problem(429),
        conflict=ResponseContract.problem(409),
        validation_failed=ResponseContract.problem(422),
        payload_too_large=ResponseContract.problem(413),
    )

    def handle_post(self, request, check_key: str):
        if request.query_params:
            raise BadRequest("This endpoint accepts no query parameters.", code="invalid_query")
        if len(request.body) > MAX_BODY:
            return self.respond_problem("payload_too_large", code="payload_too_large", detail="Run exceeds 256 KiB.")
        request.data  # Parse structural/media errors before idempotency validation.
        raw_key = request.headers.get("Idempotency-Key")
        if raw_key is None:
            raise BadRequest("An Idempotency-Key header is required.", code="idempotency_key_required")
        try:
            if len(raw_key) > 64:
                raise ValueError
            idempotency_key = UUID(raw_key)
            if str(idempotency_key) != raw_key.lower():
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
        data = serializer.validated_data
        identity = request.user.identity
        failure = data.get("error") or {}
        command = LicenseCheckRunInput(
            computing_id=identity.equipment_id,
            agent_uid=identity.agent_uid,
            check_key=check_key,
            idempotency_key=idempotency_key,
            revision=data["revision"],
            sequence=data["sequence"],
            status=data["status"],
            started_at=data["started_at"],
            duration_ms=data["duration_ms"],
            is_complete=data["is_complete"],
            error_code=failure.get("code", ""),
            error_message=failure.get("message", ""),
            licenses=tuple(_reported(item) for item in data["licenses"]),
        )
        result = report_license_check(ReportLicenseCheckRunInput(identity, command))
        response = self.respond(result)
        if result.is_replayed:
            response["Idempotency-Replayed"] = "true"
        return response
