"""HTTP views for operator and agent-facing lifecycle operations."""

from __future__ import annotations

import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.agents.application import (
    EnrollAgentInput,
    create_enrollment_grant,
    enroll_agent,
    issue_grant_for_agent,
    transition_agent_state,
)
from core.agents.contracts import CreateEnrollmentGrantInput
from core.agents.exceptions import (
    AgentEnrollmentConflict,
    AgentProofInvalid,
    EnrollmentGrantInvalid,
)
from core.agents.models import AgentIdentity
from core.common.api.correlation import get_request_id
from core.routing.api.serializers import ErrorEnvelopeSerializer

from .serializers import (
    AgentDetailResponseSerializer,
    AgentHeartbeatRequestSerializer,
    AgentHeartbeatResponseSerializer,
    AgentIdentitySerializer,
    AgentInfoResponseSerializer,
    AgentListResponseSerializer,
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

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="list_agents",
        summary="List enrolled and pending agents",
        responses={
            200: OpenApiResponse(response=AgentListResponseSerializer, description="List of agents"),
            401: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unauthorized"),
        },
        tags=["Agents (Operator)"],
    )
    def get(self, request: Request) -> Response:
        agents = AgentIdentity.objects.select_related("equipment").order_by("-created")
        serializer = AgentIdentitySerializer(agents, many=True)
        return Response({"data": serializer.data}, status=status.HTTP_200_OK)

    @extend_schema(
        operation_id="create_agent_grant",
        summary="Issue a one-time enrollment grant for computing equipment",
        request=CreateAgentGrantRequestSerializer,
        responses={
            201: OpenApiResponse(response=EnrollmentGrantIssuedResponseSerializer, description="Enrollment grant issued"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Invalid request"),
            401: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unauthorized"),
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
        except AgentEnrollmentConflict as exc:
            return _error_response(status.HTTP_409_CONFLICT, "enrollment_conflict", str(exc), request)
        except Exception as exc:
            logger.exception("Failed to create agent grant: %s", exc)
            return _error_response(status.HTTP_400_BAD_REQUEST, "invalid_request", str(exc), request)

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

    permission_classes = [IsAuthenticated]

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

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="create_agent_recovery_grant",
        summary="Issue a recovery enrollment grant for an agent's equipment",
        request=CreateGrantForAgentRequestSerializer,
        responses={
            201: OpenApiResponse(response=EnrollmentGrantIssuedResponseSerializer, description="Grant issued"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Invalid request"),
            401: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unauthorized"),
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

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="revoke_agent",
        summary="Revoke an agent identity",
        responses={
            200: OpenApiResponse(response=AgentDetailResponseSerializer, description="Agent revoked"),
            401: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unauthorized"),
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

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="decommission_agent",
        summary="Decommission an agent identity",
        responses={
            200: OpenApiResponse(response=AgentDetailResponseSerializer, description="Agent decommissioned"),
            401: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unauthorized"),
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
        except Exception as exc:
            logger.exception("Unexpected error in agent enrollment: %s", exc)
            return _error_response(status.HTTP_400_BAD_REQUEST, "invalid_request", str(exc), request)

        return Response({"data": AgentIdentitySerializer(identity).data}, status=status.HTTP_201_CREATED)


class AgentHeartbeatAPIView(APIView):
    """Update agent liveness (POST /agent/heartbeat)."""

    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="agent_heartbeat",
        summary="Record agent heartbeat",
        request=AgentHeartbeatRequestSerializer,
        responses={
            200: OpenApiResponse(response=AgentHeartbeatResponseSerializer, description="Heartbeat acknowledged"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Invalid request"),
            404: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Active agent not found"),
        },
        tags=["Agents"],
    )
    def post(self, request: Request) -> Response:
        req_serializer = AgentHeartbeatRequestSerializer(data=request.data)
        if not req_serializer.is_valid():
            return _error_response(status.HTTP_400_BAD_REQUEST, "invalid_request", "Invalid heartbeat payload.", request)

        agent_uid = req_serializer.validated_data["agent_uid"]
        agent = AgentIdentity.objects.filter(agent_uid=agent_uid, state=AgentIdentity.State.ACTIVE).first()
        if agent is None:
            return _error_response(status.HTTP_404_NOT_FOUND, "agent_not_found", "Active agent not found.", request)

        now = timezone.now()
        agent.last_seen_at = now
        agent.save(update_fields=("last_seen_at", "modified"))
        return Response({"data": {"status": "ok", "last_seen_at": now}}, status=status.HTTP_200_OK)


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
                    "backend_id": backend_id,
                    "server_time": timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "capabilities": ["enrollment", "heartbeat", "reporting"],
                }
            },
            status=status.HTTP_200_OK,
        )
