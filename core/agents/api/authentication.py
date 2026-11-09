"""Signed-request authentication for device-facing ``/agent/...`` endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import authentication, permissions
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from core.agents.application import SignedAgentRequest, authenticate_agent_request
from core.agents.exceptions import AgentRequestUnauthenticated
from core.agents.models import AgentIdentity

AGENT_ID_HEADER = "X-Agent-Id"
AGENT_TIMESTAMP_HEADER = "X-Agent-Timestamp"
AGENT_NONCE_HEADER = "X-Agent-Nonce"
AGENT_SIGNATURE_HEADER = "X-Agent-Signature"
AUTH_SCHEME = "LabMango-Agent-Signature"
_FAILURE = "Agent request authentication failed."


@dataclass(frozen=True, slots=True)
class AgentPrincipal:
    """Authenticated device; never a user and never interchangeable with operator credentials."""

    identity: AgentIdentity
    is_authenticated: bool = True
    is_active: bool = True

    @property
    def pk(self) -> str:
        # Used by UserRateThrottle as the per-caller throttle key.
        return f"agent:{self.identity.agent_uid}"


class AgentSignatureAuthentication(authentication.BaseAuthentication):
    """Verify ``X-Agent-*`` headers signed with the agent's enrolled Ed25519 key.

    All four headers are required; any failure is the same ``401`` so callers cannot probe which
    agent identities exist or why a request was denied.
    """

    def authenticate(self, request: Request) -> tuple[AgentPrincipal, None]:
        meta = request.META
        agent_uid = meta.get("HTTP_X_AGENT_ID")
        timestamp = meta.get("HTTP_X_AGENT_TIMESTAMP")
        nonce = meta.get("HTTP_X_AGENT_NONCE")
        signature = meta.get("HTTP_X_AGENT_SIGNATURE")
        if not (
            isinstance(agent_uid, str)
            and isinstance(timestamp, str)
            and isinstance(nonce, str)
            and isinstance(signature, str)
            and agent_uid
            and timestamp
            and nonce
            and signature
        ):
            raise AuthenticationFailed(_FAILURE)
        evidence = SignedAgentRequest(
            agent_uid=agent_uid,
            timestamp=timestamp,
            nonce=nonce,
            signature=signature,
            method=request.method or "",
            path=request.path,
            body=request.body,
        )
        try:
            identity = authenticate_agent_request(evidence)
        except AgentRequestUnauthenticated as error:
            raise AuthenticationFailed(_FAILURE) from error
        return AgentPrincipal(identity=identity), None

    def authenticate_header(self, request: Request) -> str:
        return AUTH_SCHEME


class IsAuthenticatedAgent(permissions.BasePermission):
    """Allow only a verified ``AgentPrincipal``; user sessions and tokens are rejected."""

    def has_permission(self, request: Request, view: Any) -> bool:
        return isinstance(getattr(request, "user", None), AgentPrincipal)


class AgentSignatureAuthScheme(OpenApiAuthenticationExtension):
    target_class = "core.agents.api.authentication.AgentSignatureAuthentication"
    name = "agentSignatureAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, Any]:
        return {
            "type": "apiKey",
            "in": "header",
            "name": AGENT_SIGNATURE_HEADER,
            "description": (
                "Ed25519 signature (base64url, unpadded) by the enrolled agent key over NUL-joined: "
                "'labmango-agent-request-v1', backend_id, agent_uid, HTTP method, path, timestamp, nonce, "
                f"hex SHA-256 of the raw body. Also required: {AGENT_ID_HEADER} (agent_uid), "
                f"{AGENT_TIMESTAMP_HEADER} (unix seconds, within AGENT_REQUEST_MAX_SKEW_S) and "
                f"{AGENT_NONCE_HEADER} (base64url, at least 16 random bytes, single use)."
            ),
        }
