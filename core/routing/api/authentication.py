"""Authentication verifiers and principals for the internal routing sync API."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

import jwt
from django.conf import settings
from django.utils.crypto import constant_time_compare
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from jwt import PyJWKClient
from rest_framework import authentication, permissions, status
from rest_framework.exceptions import APIException
from rest_framework.request import Request

logger = logging.getLogger(__name__)

_JWKS_CLIENTS: dict[str, PyJWKClient] = {}


def _get_jwks_client(url: str) -> PyJWKClient:
    """Return a cached PyJWKClient instance for key caching and rotation."""
    if url not in _JWKS_CLIENTS:
        _JWKS_CLIENTS[url] = PyJWKClient(url, cache_keys=True, max_cached_keys=16)
    return _JWKS_CLIENTS[url]


class SyncAuthError(APIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_code = "unauthorized"
    default_detail = "Missing or invalid bearer token."


class SyncForbiddenError(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "forbidden"
    default_detail = "Authenticated caller lacks the sync-read scope."


class SyncUnavailableError(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "unavailable"
    default_detail = "Identity provider is temporarily unavailable."


@dataclass(frozen=True, slots=True)
class RoutingSyncPrincipal:
    """Authenticated caller for the private routing sync stream."""

    auth_method: str  # "entra_app" | "static_token"
    is_authenticated: bool = True
    pk: str = "routing_sync"

    def __str__(self) -> str:
        return f"RoutingSyncPrincipal({self.auth_method})"


class RoutingSyncAuthentication(authentication.BaseAuthentication):
    """Strict Bearer authentication supporting Method A (Entra App Token) and Method B (Static Token)."""

    def authenticate(self, request: Request) -> tuple[RoutingSyncPrincipal, str] | None:
        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise SyncAuthError("Missing or invalid bearer token.")

        token = parts[1].strip()
        if not token:
            raise SyncAuthError("Missing or invalid bearer token.")

        # Method B: Static Bearer Token
        static_hashes = getattr(settings, "ROUTING_SYNC_STATIC_TOKEN_HASHES", [])
        if static_hashes:
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            for accepted_hash in static_hashes:
                if constant_time_compare(token_hash, accepted_hash):
                    return RoutingSyncPrincipal(auth_method="static_token"), token

        # Method A: Entra Application Token (RS256)
        try:
            unverified_header = jwt.get_unverified_header(token)
        except (jwt.PyJWTError, ValueError, TypeError):
            raise SyncAuthError("Missing or invalid bearer token.")

        if unverified_header.get("alg") != "RS256":
            raise SyncAuthError("Missing or invalid bearer token.")

        jwks_url = getattr(settings, "ROUTING_SYNC_JWKS_URL", getattr(settings, "AAD_JWKS_URL", ""))
        if not jwks_url:
            raise SyncAuthError("Missing or invalid bearer token.")

        jwks_client = _get_jwks_client(jwks_url)
        try:
            signing_key = jwks_client.get_signing_key_from_jwt(token)
        except jwt.PyJWKClientConnectionError as exc:
            logger.warning("Entra JWKS connection failed: %s", exc)
            raise SyncUnavailableError("Identity provider is temporarily unavailable.") from exc
        except (jwt.PyJWKClientError, jwt.PyJWTError) as exc:
            raise SyncAuthError("Missing or invalid bearer token.") from exc

        expected_audience = getattr(
            settings,
            "ROUTING_SYNC_AUDIENCE",
            f"api://labmango-{getattr(settings, 'BACKEND_ID', 'dept_a')}",
        )
        try:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=expected_audience,
                leeway=60,
                options={"verify_exp": True, "verify_aud": True},
            )
        except jwt.ExpiredSignatureError as exc:
            raise SyncAuthError("Missing or invalid bearer token.") from exc
        except jwt.InvalidAudienceError as exc:
            raise SyncAuthError("Missing or invalid bearer token.") from exc
        except jwt.PyJWTError as exc:
            raise SyncAuthError("Missing or invalid bearer token.") from exc

        allowed_tenants = getattr(settings, "ROUTING_SYNC_ENTRA_TENANT_IDS", [])
        issuer = payload.get("iss", "")
        valid_issuers = {f"https://login.microsoftonline.com/{tid}/v2.0" for tid in allowed_tenants}
        if issuer not in valid_issuers:
            raise SyncAuthError("Missing or invalid bearer token.")

        # Application-only check: no delegated scopes
        if "scp" in payload:
            raise SyncForbiddenError("Authenticated caller lacks the sync-read scope.")
        if payload.get("idtyp") and payload.get("idtyp") != "app":
            raise SyncForbiddenError("Authenticated caller lacks the sync-read scope.")

        required_role = getattr(settings, "ROUTING_SYNC_REQUIRED_ROLE", "Routing.Sync.Read")
        roles = payload.get("roles", [])
        if required_role not in roles:
            raise SyncForbiddenError("Authenticated caller lacks the sync-read scope.")

        return RoutingSyncPrincipal(auth_method="entra_app"), token

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"


class IsRoutingSyncAuthenticated(permissions.BasePermission):
    """Requires caller to be an authenticated RoutingSyncPrincipal."""

    def has_permission(self, request: Request, view: Any) -> bool:
        principal = getattr(request, "user", None)
        if isinstance(principal, RoutingSyncPrincipal) and principal.is_authenticated:
            return True
        return False


class RoutingSyncAuthScheme(OpenApiAuthenticationExtension):
    target_class = "core.routing.api.authentication.RoutingSyncAuthentication"
    name = "routingSyncBearerAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, Any]:
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
