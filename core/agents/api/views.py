"""HTTP views for operator and agent-facing lifecycle operations."""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.agents.api.authentication import AgentPrincipal, AgentSignatureAuthentication, IsAuthenticatedAgent
from core.agents.application import (
    EnrollAgentInput,
    create_enrollment_grant,
    enroll_agent,
    issue_grant_for_agent,
    record_agent_heartbeat,
    transition_agent_state,
)
from core.agents.contracts import CreateEnrollmentGrantInput
from core.agents.exceptions import (
    AgentEnrollmentConflict,
    AgentEquipmentNotFound,
    AgentProofInvalid,
    AgentRequestUnauthenticated,
    EnrollmentGrantInvalid,
)
from core.agents.models import AgentIdentity
from core.common.api.correlation import get_request_id
from core.common.api.pagination import ResultsSetPagination
from core.labs.features.bench_bookings.public import (
    AgentExtensionBenchNotFree,
    AgentExtensionNotAllowed,
    CheckAgentBookingLoginInput,
    CheckInAgentBookingInput,
    CompleteAgentBookingInput,
    ExtendAgentBookingInput,
    check_agent_booking_login,
    check_in_agent_booking,
    complete_agent_booking,
    extend_agent_booking,
)
from core.labs.features.equipment.public import SyncComputingActivityInput, sync_computing_activity
from core.labs.features.lab_sessions.public import (
    RecordSessionLogInput,
    SessionLogConflict,
    SessionLogEquipmentUnavailable,
    SessionLogInvalid,
    record_session_log,
)
from core.labs.models import Equipment
from core.routing.api.serializers import ErrorEnvelopeSerializer
from core.users.public import IsLabCoordinator

from .serializers import (
    AgentActivityDataSerializer,
    AgentActivityReportSerializer,
    AgentActivityResponseSerializer,
    AgentBookingCheckInDataSerializer,
    AgentBookingCheckInResponseSerializer,
    AgentBookingCompleteDataSerializer,
    AgentBookingCompleteResponseSerializer,
    AgentBookingExtendDataSerializer,
    AgentBookingExtendErrorSerializer,
    AgentBookingExtendRequestSerializer,
    AgentBookingExtendResponseSerializer,
    AgentBookingValidationDataSerializer,
    AgentBookingValidationRequestSerializer,
    AgentBookingValidationResponseSerializer,
    AgentDetailResponseSerializer,
    AgentHeartbeatRequestSerializer,
    AgentHeartbeatResponseSerializer,
    AgentIdentitySerializer,
    AgentInfoResponseSerializer,
    AgentListResponseSerializer,
    AgentSessionLogDataSerializer,
    AgentSessionLogReportSerializer,
    AgentSessionLogResponseSerializer,
    CreateAgentGrantRequestSerializer,
    CreateGrantForAgentRequestSerializer,
    EnrollAgentRequestSerializer,
    EnrollmentGrantIssuedResponseSerializer,
)

logger = logging.getLogger(__name__)


def _error_response(status_code: int, code: str, message: str, request: Request, details: list | None = None) -> Response:
    req_id = get_request_id(request)
    return Response(
        {
            "error": {
                "code": code,
                "message": message,
                "details": details if details is not None else [],
                "request_id": req_id,
            }
        },
        status=status_code,
    )


class AgentListCreateAPIView(APIView):
    """List agent identities or issue an initial enrollment grant."""

    # Reads: any authenticated user. Writes (grants, revoke, decommission): lab coordinators and admins.
    permission_classes = [IsLabCoordinator]

    @extend_schema(
        operation_id="list_agents",
        summary="List enrolled and pending agents",
        parameters=[
            OpenApiParameter(
                "page",
                {"type": "integer", "minimum": 1},
                OpenApiParameter.QUERY,
                required=False,
                description="Page number (>= 1)",
            ),
            OpenApiParameter(
                "page_size",
                {"type": "integer", "minimum": 1, "maximum": 100},
                OpenApiParameter.QUERY,
                required=False,
                description="Page size (1..100, default 25)",
            ),
        ],
        responses={
            200: OpenApiResponse(response=AgentListResponseSerializer, description="Page of agents"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Invalid page or page_size"),
            404: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Page out of range"),
            401: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unauthorized"),
        },
        tags=["Agents (Operator)"],
    )
    def get(self, request: Request) -> Response:
        # COL-1: bounded page-number pagination; pk tie-breaker keeps pages stable.
        agents = AgentIdentity.objects.select_related("equipment").order_by("-created", "-pk")
        paginator = ResultsSetPagination()
        page = paginator.paginate_queryset(agents, request, view=self)
        return paginator.get_paginated_response(AgentIdentitySerializer(page, many=True).data)

    @extend_schema(
        operation_id="create_agent_grant",
        summary="Issue a one-time enrollment grant for computing equipment",
        request=CreateAgentGrantRequestSerializer,
        responses={
            201: OpenApiResponse(response=EnrollmentGrantIssuedResponseSerializer, description="Enrollment grant issued"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Invalid request"),
            401: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unauthorized"),
            403: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Caller is not a lab coordinator or admin"),
            404: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Computing equipment not found"),
            409: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Equipment already has pending or active agent"),
        },
        tags=["Agents (Operator)"],
    )
    def post(self, request: Request) -> Response:
        req_serializer = CreateAgentGrantRequestSerializer(data=request.data)
        if not req_serializer.is_valid():
            return _error_response(
                status.HTTP_400_BAD_REQUEST,
                "invalid_request",
                "Invalid grant request parameters.",
                request,
                details=[{"field": k, "message": str(v[0])} for k, v in req_serializer.errors.items()],
            )

        cmd = CreateEnrollmentGrantInput(
            equipment_uid=req_serializer.validated_data["equipment_uid"],
            ttl_minutes=req_serializer.validated_data["ttl_minutes"],
        )
        try:
            issued = create_enrollment_grant(cmd, actor=request.user)
        except AgentEquipmentNotFound as exc:
            return _error_response(status.HTTP_404_NOT_FOUND, "equipment_not_found", str(exc), request)
        except AgentEnrollmentConflict as exc:
            return _error_response(status.HTTP_409_CONFLICT, "enrollment_conflict", str(exc), request)

        return Response(
            {
                "data": {
                    "agent_uid": str(issued.agent_uid),
                    "equipment_uid": str(issued.equipment_uid),
                    "grant": issued.grant,
                    "expires_at": issued.expires_at,
                }
            },
            status=status.HTTP_201_CREATED,
        )


class AgentDetailAPIView(APIView):
    """Retrieve detail of an enrolled agent."""

    # Reads: any authenticated user. Writes (grants, revoke, decommission): lab coordinators and admins.
    permission_classes = [IsLabCoordinator]

    @extend_schema(
        operation_id="get_agent_detail",
        summary="Retrieve agent identity detail",
        responses={
            200: OpenApiResponse(response=AgentDetailResponseSerializer, description="Agent detail"),
            401: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unauthorized"),
            404: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Agent not found"),
        },
        tags=["Agents (Operator)"],
    )
    def get(self, request: Request, pk: int) -> Response:
        agent = get_object_or_404(AgentIdentity.objects.select_related("equipment"), pk=pk)
        return Response({"data": AgentIdentitySerializer(agent).data}, status=status.HTTP_200_OK)


class AgentGrantCreateAPIView(APIView):
    """Issue a new or recovery enrollment grant for an existing agent."""

    # Reads: any authenticated user. Writes (grants, revoke, decommission): lab coordinators and admins.
    permission_classes = [IsLabCoordinator]

    @extend_schema(
        operation_id="create_agent_recovery_grant",
        summary="Issue a recovery enrollment grant for an agent's equipment",
        request=CreateGrantForAgentRequestSerializer,
        responses={
            201: OpenApiResponse(response=EnrollmentGrantIssuedResponseSerializer, description="Grant issued"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Invalid request"),
            401: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unauthorized"),
            403: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Caller is not a lab coordinator or admin"),
            404: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Agent not found"),
            409: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Enrollment conflict"),
        },
        tags=["Agents (Operator)"],
    )
    def post(self, request: Request, pk: int) -> Response:
        agent = get_object_or_404(AgentIdentity.objects.select_related("equipment"), pk=pk)
        req_serializer = CreateGrantForAgentRequestSerializer(data=request.data)
        if not req_serializer.is_valid():
            return _error_response(
                status.HTTP_400_BAD_REQUEST,
                "invalid_request",
                "Invalid parameters.",
                request,
            )

        try:
            ttl = req_serializer.validated_data.get("ttl_minutes", 15)
            issued = issue_grant_for_agent(agent.pk, ttl, actor=request.user)
        except AgentEnrollmentConflict as exc:
            return _error_response(status.HTTP_409_CONFLICT, "enrollment_conflict", str(exc), request)

        return Response(
            {
                "data": {
                    "agent_uid": str(issued.agent_uid),
                    "equipment_uid": str(issued.equipment_uid),
                    "grant": issued.grant,
                    "expires_at": issued.expires_at,
                }
            },
            status=status.HTTP_201_CREATED,
        )


class AgentRevokeActionAPIView(APIView):
    """Revoke an active agent identity."""

    # Reads: any authenticated user. Writes (grants, revoke, decommission): lab coordinators and admins.
    permission_classes = [IsLabCoordinator]

    @extend_schema(
        operation_id="revoke_agent",
        summary="Revoke an agent identity",
        responses={
            200: OpenApiResponse(response=AgentDetailResponseSerializer, description="Agent revoked"),
            401: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unauthorized"),
            403: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Caller is not a lab coordinator or admin"),
            404: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Agent not found"),
            409: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Conflict"),
        },
        tags=["Agents (Operator)"],
    )
    def post(self, request: Request, pk: int) -> Response:
        agent = get_object_or_404(AgentIdentity, pk=pk)
        try:
            updated = transition_agent_state(agent.agent_uid, AgentIdentity.State.REVOKED, actor=request.user)
        except AgentEnrollmentConflict as exc:
            return _error_response(status.HTTP_409_CONFLICT, "conflict", str(exc), request)

        return Response({"data": AgentIdentitySerializer(updated).data}, status=status.HTTP_200_OK)


class AgentDecommissionActionAPIView(APIView):
    """Decommission an active agent identity."""

    # Reads: any authenticated user. Writes (grants, revoke, decommission): lab coordinators and admins.
    permission_classes = [IsLabCoordinator]

    @extend_schema(
        operation_id="decommission_agent",
        summary="Decommission an agent identity",
        responses={
            200: OpenApiResponse(response=AgentDetailResponseSerializer, description="Agent decommissioned"),
            401: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unauthorized"),
            403: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Caller is not a lab coordinator or admin"),
            404: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Agent not found"),
            409: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Conflict"),
        },
        tags=["Agents (Operator)"],
    )
    def post(self, request: Request, pk: int) -> Response:
        agent = get_object_or_404(AgentIdentity, pk=pk)
        try:
            updated = transition_agent_state(agent.agent_uid, AgentIdentity.State.DECOMMISSIONED, actor=request.user)
        except AgentEnrollmentConflict as exc:
            return _error_response(status.HTTP_409_CONFLICT, "conflict", str(exc), request)

        return Response({"data": AgentIdentitySerializer(updated).data}, status=status.HTTP_200_OK)


class AgentEnrollmentAPIView(APIView):
    """Redeem an enrollment grant with agent proof (POST /agent/enrollments)."""

    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="enroll_agent",
        summary="Redeem one-time grant with agent private key proof",
        request=EnrollAgentRequestSerializer,
        responses={
            201: OpenApiResponse(response=AgentDetailResponseSerializer, description="Agent successfully enrolled"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Invalid grant or proof"),
            409: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Enrollment conflict"),
        },
        tags=["Agents"],
    )
    def post(self, request: Request) -> Response:
        req_serializer = EnrollAgentRequestSerializer(data=request.data)
        if not req_serializer.is_valid():
            return _error_response(
                status.HTTP_400_BAD_REQUEST,
                "invalid_request",
                "Invalid enrollment payload.",
                request,
                details=[{"field": k, "message": str(v[0])} for k, v in req_serializer.errors.items()],
            )

        cmd = EnrollAgentInput(
            grant=req_serializer.validated_data["grant"],
            public_key=req_serializer.validated_data["public_key"],
            key_storage=req_serializer.validated_data["key_storage"],
            fingerprint=req_serializer.validated_data.get("fingerprint", ""),
            agent_version=req_serializer.validated_data["agent_version"],
            proof=req_serializer.validated_data["proof"],
        )
        try:
            identity = enroll_agent(cmd)
        except EnrollmentGrantInvalid as exc:
            return _error_response(status.HTTP_400_BAD_REQUEST, "invalid_grant", str(exc), request)
        except AgentProofInvalid as exc:
            return _error_response(status.HTTP_400_BAD_REQUEST, "invalid_proof", str(exc), request)
        except AgentEnrollmentConflict as exc:
            return _error_response(status.HTTP_409_CONFLICT, "enrollment_conflict", str(exc), request)
        except ValueError as exc:
            # Raised only with fixed, client-safe messages by enroll_agent's metadata checks.
            return _error_response(status.HTTP_400_BAD_REQUEST, "invalid_request", str(exc), request)

        return Response({"data": AgentIdentitySerializer(identity).data}, status=status.HTTP_201_CREATED)


class AgentHeartbeatAPIView(APIView):
    """Update agent liveness (POST /agent/heartbeat) for a request signed by the agent's enrolled key."""

    authentication_classes = [AgentSignatureAuthentication]
    permission_classes = [IsAuthenticatedAgent]

    @extend_schema(
        operation_id="agent_heartbeat",
        summary="Record agent heartbeat",
        description=(
            "Requires the X-Agent-Id, X-Agent-Timestamp, X-Agent-Nonce and X-Agent-Signature headers "
            "(see the agentSignatureAuth security scheme). The body may repeat agent_uid; if present it "
            "must equal X-Agent-Id."
        ),
        request=AgentHeartbeatRequestSerializer,
        responses={
            200: OpenApiResponse(response=AgentHeartbeatResponseSerializer, description="Heartbeat acknowledged"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Invalid request"),
            401: OpenApiResponse(
                response=ErrorEnvelopeSerializer,
                description="Missing, invalid, stale or replayed signature, or agent not active",
            ),
            429: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Request rate exceeded"),
        },
        tags=["Agents"],
    )
    def post(self, request: Request) -> Response:
        req_serializer = AgentHeartbeatRequestSerializer(data=request.data)
        if not req_serializer.is_valid():
            return _error_response(status.HTTP_400_BAD_REQUEST, "invalid_request", "Invalid heartbeat payload.", request)

        principal = request.user
        if not isinstance(principal, AgentPrincipal):  # guaranteed by IsAuthenticatedAgent
            raise AuthenticationFailed("Agent request authentication failed.")
        identity = principal.identity
        body_uid = req_serializer.validated_data.get("agent_uid")
        if body_uid is not None and body_uid != identity.agent_uid:
            return _error_response(
                status.HTTP_400_BAD_REQUEST,
                "invalid_request",
                "agent_uid does not match the authenticated agent.",
                request,
            )
        try:
            seen_at = record_agent_heartbeat(identity)
        except AgentRequestUnauthenticated:
            raise AuthenticationFailed("Agent request authentication failed.") from None
        return Response({"data": {"status": "ok", "last_seen_at": seen_at}}, status=status.HTTP_200_OK)


class AgentActivityAPIView(APIView):
    """Report the live activity of the agent's own computer (PATCH /agent/equipment/activity).

    The computer is the one the signing agent is enrolled for (``AgentIdentity.equipment``); the
    request never names equipment. Race guard and idempotency come from the equipment command
    (activity row lock; repeating a report changes nothing but the report time).
    """

    authentication_classes = [AgentSignatureAuthentication]
    permission_classes = [IsAuthenticatedAgent]

    @extend_schema(
        operation_id="agent_report_activity",
        summary="Report live activity of the agent's computer",
        description=(
            "Requires the X-Agent-Id, X-Agent-Timestamp, X-Agent-Nonce and X-Agent-Signature headers "
            "(see the agentSignatureAuth security scheme). Send only the fields that changed."
        ),
        request=AgentActivityReportSerializer,
        responses={
            200: OpenApiResponse(response=AgentActivityResponseSerializer, description="Activity recorded"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Body is not a JSON object"),
            401: OpenApiResponse(
                response=ErrorEnvelopeSerializer,
                description="Missing, invalid, stale or replayed signature, or agent not active",
            ),
            409: OpenApiResponse(
                response=ErrorEnvelopeSerializer,
                description="The agent's computer was deleted or is no longer computing equipment",
            ),
            422: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unknown field or invalid value"),
            429: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Request rate exceeded"),
        },
        tags=["Agents"],
    )
    def patch(self, request: Request) -> Response:
        if not isinstance(request.data, dict):
            return _error_response(status.HTTP_400_BAD_REQUEST, "invalid_request", "Send a JSON object.", request)
        req_serializer = AgentActivityReportSerializer(data=request.data)
        unknown = sorted(set(request.data) - set(req_serializer.fields))
        if unknown or not req_serializer.is_valid():
            details = [{"field": name, "message": "Unknown or read-only field."} for name in unknown]
            if not unknown:
                details = [{"field": k, "message": str(v[0])} for k, v in req_serializer.errors.items()]
            return _error_response(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "validation_failed", "Invalid activity report.", request, details
            )
        principal = request.user
        if not isinstance(principal, AgentPrincipal):  # guaranteed by IsAuthenticatedAgent
            raise AuthenticationFailed("Agent request authentication failed.")
        try:
            activity = sync_computing_activity(
                SyncComputingActivityInput(
                    computing_id=principal.identity.equipment_id,
                    fields=tuple(req_serializer.validated_data.items()),
                ),
                actor=None,  # an agent report: refreshes last_agent_report_at
            )
        except Equipment.DoesNotExist:
            return _error_response(
                status.HTTP_409_CONFLICT,
                "equipment_unavailable",
                "The computer this agent is enrolled for is deleted or no longer computing equipment.",
                request,
            )
        except ValidationError as error:
            details = [{"field": k, "message": str(v[0])} for k, v in error.message_dict.items()]
            return _error_response(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "validation_failed", "Invalid activity report.", request, details
            )
        return Response({"data": AgentActivityDataSerializer(activity).data}, status=status.HTTP_200_OK)


def _validation_details(serializer, unknown: list[str]) -> list[dict[str, str]]:
    if unknown:
        return [{"field": name, "message": "Unknown or read-only field."} for name in unknown]
    return [{"field": k, "message": str(v[0])} for k, v in serializer.errors.items()]


def _signing_identity(request: Request) -> AgentIdentity:
    principal = request.user
    if not isinstance(principal, AgentPrincipal):  # guaranteed by IsAuthenticatedAgent
        raise AuthenticationFailed("Agent request authentication failed.")
    return principal.identity


class AgentSessionLogAPIView(APIView):
    """Store one completed remote session (POST /agent/session-logs), pushed once after logout.

    The computer is the one the signing agent is enrolled for. Race guard and idempotency come from
    ``lab_sessions.record_session_log`` (unique computer, agent and event id).
    """

    authentication_classes = [AgentSignatureAuthentication]
    permission_classes = [IsAuthenticatedAgent]

    @extend_schema(
        operation_id="agent_record_session_log",
        summary="Record a completed remote session",
        description=(
            "Requires the X-Agent-Id, X-Agent-Timestamp, X-Agent-Nonce and X-Agent-Signature headers "
            "(see the agentSignatureAuth security scheme). Send once after logout. Repeat the same "
            "event_id when retrying: identical values return 200 with the stored record. Rejected when "
            "logout is more than 5 minutes ahead of server time, login is more than 7 days old, or active "
            "time exceeds the time between login and logout."
        ),
        request=AgentSessionLogReportSerializer,
        responses={
            201: OpenApiResponse(response=AgentSessionLogResponseSerializer, description="Session stored"),
            200: OpenApiResponse(
                response=AgentSessionLogResponseSerializer, description="Same event already stored; no change"
            ),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Body is not a JSON object"),
            401: OpenApiResponse(
                response=ErrorEnvelopeSerializer,
                description="Missing, invalid, stale or replayed signature, or agent not active",
            ),
            409: OpenApiResponse(
                response=ErrorEnvelopeSerializer,
                description="Event id stored with different values, or the agent's computer is deleted",
            ),
            422: OpenApiResponse(
                response=ErrorEnvelopeSerializer, description="Unknown field, invalid value or limit exceeded"
            ),
            429: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Request rate exceeded"),
        },
        tags=["Agents"],
    )
    def post(self, request: Request) -> Response:
        if not isinstance(request.data, dict):
            return _error_response(status.HTTP_400_BAD_REQUEST, "invalid_request", "Send a JSON object.", request)
        serializer = AgentSessionLogReportSerializer(data=request.data)
        unknown = sorted(set(request.data) - set(serializer.fields))
        if unknown or not serializer.is_valid():
            return _error_response(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "validation_failed",
                "Invalid session log.",
                request,
                _validation_details(serializer, unknown),
            )
        identity = _signing_identity(request)
        values = serializer.validated_data
        try:
            record = record_session_log(
                RecordSessionLogInput(
                    equipment_id=identity.equipment_id,
                    agent_id=str(identity.agent_uid),
                    event_id=values["event_id"],
                    login_time=values["login_time"],
                    logout_time=values["logout_time"],
                    active_duration_seconds=values["active_duration_seconds"],
                    remote_user=values["remote_user"],
                    remote_ip=values.get("remote_ip"),
                    remote_host=values.get("remote_host"),
                    booking_code=values.get("booking_code"),
                    agent_version=values.get("agent_version", ""),
                ),
                actor=None,  # an agent report, not a user action
            )
        except SessionLogInvalid as error:
            # ERR-6: name the request field, not the stored column.
            wire = {"event_id": "event_key", "login_time": "login_at", "logout_time": "logout_at"}
            details = [{"field": wire.get(k, k), "message": str(v)} for k, v in (error.details or {}).items()]
            return _error_response(
                status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, "Invalid session log.", request, details
            )
        except (SessionLogConflict, SessionLogEquipmentUnavailable) as error:
            return _error_response(status.HTTP_409_CONFLICT, error.code, error.message, request)
        return Response(
            {"data": AgentSessionLogDataSerializer(record).data},
            status=status.HTTP_201_CREATED if record.created else status.HTTP_200_OK,
        )


class AgentBookingValidationAPIView(APIView):
    """Check a booking code before login (POST /agent/bookings/actions/validate). Read-only.

    Eligible only for an approved booking on the bench of the agent's own computer, inside its usable
    window. Every other case gets the same ``eligible: false`` answer.
    """

    authentication_classes = [AgentSignatureAuthentication]
    permission_classes = [IsAuthenticatedAgent]

    @extend_schema(
        operation_id="agent_validate_booking",
        summary="Check whether a booking code may be used to log in on this computer now",
        description=(
            "Requires the X-Agent-Id, X-Agent-Timestamp, X-Agent-Nonce and X-Agent-Signature headers "
            "(see the agentSignatureAuth security scheme). Does not check in or change the booking. "
            "Unknown, unapproved, cancelled, finished, other-bench and out-of-window codes all return "
            "eligible: false with no other fields."
        ),
        request=AgentBookingValidationRequestSerializer,
        responses={
            200: OpenApiResponse(response=AgentBookingValidationResponseSerializer, description="Eligibility"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Body is not a JSON object"),
            401: OpenApiResponse(
                response=ErrorEnvelopeSerializer,
                description="Missing, invalid, stale or replayed signature, or agent not active",
            ),
            422: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unknown field or invalid code"),
            429: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Request rate exceeded"),
        },
        tags=["Agents"],
    )
    def post(self, request: Request) -> Response:
        if not isinstance(request.data, dict):
            return _error_response(status.HTTP_400_BAD_REQUEST, "invalid_request", "Send a JSON object.", request)
        serializer = AgentBookingValidationRequestSerializer(data=request.data)
        unknown = sorted(set(request.data) - set(serializer.fields))
        if unknown or not serializer.is_valid():
            return _error_response(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "validation_failed",
                "Invalid booking validation request.",
                request,
                _validation_details(serializer, unknown),
            )
        identity = _signing_identity(request)
        login = check_agent_booking_login(
            CheckAgentBookingLoginInput(
                equipment_id=identity.equipment_id,
                booking_code=serializer.validated_data["booking_code"],
            )
        )
        if login is None:
            # A fixed body, not serialized: the same bytes for every failure, with no null fields.
            return Response({"data": {"is_eligible": False}}, status=status.HTTP_200_OK)
        data = {
            "is_eligible": True,
            "booking_code": login.booking_code,
            "starts_at": login.starts_at,
            "ends_at": login.ends_at,
            "booked_for": login.booked_for,
        }
        return Response({"data": AgentBookingValidationDataSerializer(data).data}, status=status.HTTP_200_OK)


class AgentBookingCheckInAPIView(APIView):
    """Check a user in with a booking code (POST /agent/bookings/actions/check-in).

    Same eligibility as validation. A reserved booking becomes in progress; checking in again on an
    in-progress booking succeeds without change. Every failure gets the same ``checked_in: false``.
    """

    authentication_classes = [AgentSignatureAuthentication]
    permission_classes = [IsAuthenticatedAgent]

    @extend_schema(
        operation_id="agent_check_in_booking",
        summary="Check a user in with a booking code; the booking becomes in progress",
        description=(
            "Requires the X-Agent-Id, X-Agent-Timestamp, X-Agent-Nonce and X-Agent-Signature headers "
            "(see the agentSignatureAuth security scheme). Call when the user enters a booking code at "
            "login. Eligible only for an approved booking on this computer's bench, from its start until "
            "10 minutes later (reserved) or until it ends (in progress). Repeating a check-in is safe. "
            "Every failure returns checked_in: false with no other fields."
        ),
        request=AgentBookingValidationRequestSerializer,
        responses={
            200: OpenApiResponse(response=AgentBookingCheckInResponseSerializer, description="Check-in result"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Body is not a JSON object"),
            401: OpenApiResponse(
                response=ErrorEnvelopeSerializer,
                description="Missing, invalid, stale or replayed signature, or agent not active",
            ),
            422: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unknown field or invalid code"),
            429: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Request rate exceeded"),
        },
        tags=["Agents"],
    )
    def post(self, request: Request) -> Response:
        if not isinstance(request.data, dict):
            return _error_response(status.HTTP_400_BAD_REQUEST, "invalid_request", "Send a JSON object.", request)
        serializer = AgentBookingValidationRequestSerializer(data=request.data)
        unknown = sorted(set(request.data) - set(serializer.fields))
        if unknown or not serializer.is_valid():
            return _error_response(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "validation_failed",
                "Invalid booking check-in request.",
                request,
                _validation_details(serializer, unknown),
            )
        identity = _signing_identity(request)
        check_in = check_in_agent_booking(
            CheckInAgentBookingInput(
                agent_uid=identity.agent_uid,
                booking_code=serializer.validated_data["booking_code"],
            ),
            actor=None,  # an agent action, not a user action
        )
        if check_in is None:
            # A fixed body, not serialized: the same bytes for every failure, with no null fields.
            return Response({"data": {"is_checked_in": False}}, status=status.HTTP_200_OK)
        data = {
            "is_checked_in": True,
            "booking_code": check_in.booking_code,
            "starts_at": check_in.starts_at,
            "ends_at": check_in.ends_at,
            "booked_for": check_in.booked_for,
        }
        return Response({"data": AgentBookingCheckInDataSerializer(data).data}, status=status.HTTP_200_OK)


class AgentBookingCompleteAPIView(APIView):
    """End a booking at the user's request (POST /agent/bookings/actions/complete).

    Only an in-progress booking on the agent's own bench can be ended; ending it again succeeds
    without change. Bookings nobody ends are completed at their end time by the scheduled job.
    Every failure gets the same ``completed: false``.
    """

    authentication_classes = [AgentSignatureAuthentication]
    permission_classes = [IsAuthenticatedAgent]

    @extend_schema(
        operation_id="agent_complete_booking",
        summary="End a booking at the user's request; the booking becomes completed",
        description=(
            "Requires the X-Agent-Id, X-Agent-Timestamp, X-Agent-Nonce and X-Agent-Signature headers "
            "(see the agentSignatureAuth security scheme). Call only when the user chooses to end the "
            "booking, not at every logout. Only an approved, in-progress booking on this computer's bench "
            "can be ended; repeating the call is safe. The booked end time is not changed. Every failure "
            "returns completed: false with no other fields."
        ),
        request=AgentBookingValidationRequestSerializer,
        responses={
            200: OpenApiResponse(response=AgentBookingCompleteResponseSerializer, description="End result"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Body is not a JSON object"),
            401: OpenApiResponse(
                response=ErrorEnvelopeSerializer,
                description="Missing, invalid, stale or replayed signature, or agent not active",
            ),
            422: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unknown field or invalid code"),
            429: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Request rate exceeded"),
        },
        tags=["Agents"],
    )
    def post(self, request: Request) -> Response:
        if not isinstance(request.data, dict):
            return _error_response(status.HTTP_400_BAD_REQUEST, "invalid_request", "Send a JSON object.", request)
        serializer = AgentBookingValidationRequestSerializer(data=request.data)
        unknown = sorted(set(request.data) - set(serializer.fields))
        if unknown or not serializer.is_valid():
            return _error_response(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "validation_failed",
                "Invalid booking end request.",
                request,
                _validation_details(serializer, unknown),
            )
        identity = _signing_identity(request)
        ended = complete_agent_booking(
            CompleteAgentBookingInput(
                agent_uid=identity.agent_uid,
                booking_code=serializer.validated_data["booking_code"],
            ),
            actor=None,  # an agent action on the user's request, not a user session
        )
        if ended is None:
            # A fixed body, not serialized: the same bytes for every failure, with no null fields.
            return Response({"data": {"is_completed": False}}, status=status.HTTP_200_OK)
        data = {
            "is_completed": True,
            "booking_code": ended.booking_code,
            "starts_at": ended.starts_at,
            "ends_at": ended.ends_at,
        }
        return Response({"data": AgentBookingCompleteDataSerializer(data).data}, status=status.HTTP_200_OK)


def _extension_refusal(request: Request, status_code: int, code: str, message: str, reason: str, limit) -> Response:
    detail = {
        "field": "ends_at",
        "code": reason,
        "message": message,
        "limit_at": serializers.DateTimeField().to_representation(limit) if limit is not None else None,
    }
    return _error_response(status_code, code, message, request, [detail])


class AgentBookingExtendAPIView(APIView):
    """Extend a running booking at the user's request (POST /agent/bookings/actions/extend).

    Only an approved in-progress booking on the agent's own bench can be extended, by at least
    10 minutes, up to 4 hours in total. Unknown or foreign bookings get ``extended: false``; a refused
    extension of the agent's own booking says why, so the agent can offer an alternative.
    """

    authentication_classes = [AgentSignatureAuthentication]
    permission_classes = [IsAuthenticatedAgent]

    @extend_schema(
        operation_id="agent_extend_booking",
        summary="Extend a running booking at the user's request",
        description=(
            "Requires the X-Agent-Id, X-Agent-Timestamp, X-Agent-Nonce and X-Agent-Signature headers "
            "(see the agentSignatureAuth security scheme). Only an approved, in-progress booking on this "
            "computer's bench can be extended: at least 10 minutes later than the current end, before the "
            "current end has passed, without overlapping the next booking, and at most 4 hours from the "
            "start (longer bookings need approval in the web app). Seconds are dropped. Repeating the "
            "same end time is safe. An unknown or foreign booking returns extended: false with no other "
            "fields."
        ),
        request=AgentBookingExtendRequestSerializer,
        responses={
            200: OpenApiResponse(response=AgentBookingExtendResponseSerializer, description="Extension result"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Body is not a JSON object"),
            401: OpenApiResponse(
                response=ErrorEnvelopeSerializer,
                description="Missing, invalid, stale or replayed signature, or agent not active",
            ),
            409: OpenApiResponse(
                response=AgentBookingExtendErrorSerializer,
                description="bench_not_free: another booking starts at details[0].limit_at",
            ),
            422: OpenApiResponse(
                # DOC-4: one envelope; its details items are a refusal or a validation item.
                response=AgentBookingExtendErrorSerializer,
                description=(
                    "validation_failed: unknown field or invalid value (generic error envelope); "
                    "extension_not_allowed: details[0].code says why (already_ended, not_later, too_short, "
                    "needs_approval, bench_not_in_service) and details[0].limit_at gives the bound"
                ),
            ),
            429: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Request rate exceeded"),
        },
        tags=["Agents"],
    )
    def post(self, request: Request) -> Response:
        if not isinstance(request.data, dict):
            return _error_response(status.HTTP_400_BAD_REQUEST, "invalid_request", "Send a JSON object.", request)
        serializer = AgentBookingExtendRequestSerializer(data=request.data)
        unknown = sorted(set(request.data) - set(serializer.fields))
        if unknown or not serializer.is_valid():
            return _error_response(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "validation_failed",
                "Invalid booking extension request.",
                request,
                _validation_details(serializer, unknown),
            )
        identity = _signing_identity(request)
        try:
            extended = extend_agent_booking(
                ExtendAgentBookingInput(
                    agent_uid=identity.agent_uid,
                    booking_code=serializer.validated_data["booking_code"],
                    ends_at=serializer.validated_data["ends_at"],
                ),
                actor=None,  # an agent action on the user's request, not a user session
            )
        except AgentExtensionNotAllowed as error:
            details = error.details or {}
            return _extension_refusal(
                request,
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                error.code,
                error.message,
                details.get("reason", ""),
                details.get("limit"),
            )
        except AgentExtensionBenchNotFree as error:
            return _extension_refusal(
                request,
                status.HTTP_409_CONFLICT,
                error.code,
                error.message,
                error.code,
                (error.details or {}).get("available_until"),
            )
        if extended is None:
            # A fixed body, not serialized: the same bytes for every failure, with no null fields.
            return Response({"data": {"is_extended": False}}, status=status.HTTP_200_OK)
        data = {
            "is_extended": True,
            "booking_code": extended.booking_code,
            "starts_at": extended.starts_at,
            "ends_at": extended.ends_at,
        }
        return Response({"data": AgentBookingExtendDataSerializer(data).data}, status=status.HTTP_200_OK)


class AgentInfoAPIView(APIView):
    """Discover agent capabilities and backend metadata (GET /agent/info)."""

    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="get_agent_info",
        summary="Discover agent API capabilities and server identity",
        responses={
            200: OpenApiResponse(response=AgentInfoResponseSerializer, description="Server agent metadata"),
            401: OpenApiResponse(
                response=ErrorEnvelopeSerializer, description="Supplied bearer credentials are invalid"
            ),
            429: OpenApiResponse(
                response=ErrorEnvelopeSerializer, description="Anonymous or user request rate exceeded"
            ),
        },
        tags=["Agents"],
    )
    def get(self, request: Request) -> Response:
        backend_id = getattr(settings, "BACKEND_ID", "dept_a")
        return Response(
            {
                "data": {
                    "backend_key": backend_id,
                    "server_time": timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "capabilities": [
                        "enrollment",
                        "heartbeat",
                        "reporting",
                        "activity",
                        "request_signature_v1",
                        "session_logs",
                        "booking_validation",
                        "booking_check_in",
                        "booking_complete",
                        "booking_extend",
                    ],
                    "endpoints": {
                        "session_logs": reverse("agent-session-logs"),
                        "booking_validation": reverse("agent-booking-validation"),
                        "booking_check_in": reverse("agent-booking-check-in"),
                        "booking_complete": reverse("agent-booking-complete"),
                        "booking_extend": reverse("agent-booking-extend"),
                    },
                }
            },
            status=status.HTTP_200_OK,
        )
