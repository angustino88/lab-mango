"""Microsoft Entra access tokens for desktop clients (the audit tool) on the endpoints that opt in.

The browser frontend keeps its own flow (ID token exchanged at ``/api/aad-login`` for a Lab Mango JWT).
Desktop clients cannot use that flow, so selected views also accept an Entra **access token** issued for
the scope the existing frontend app registration exposes (``ENTRA_API_AUDIT_SCOPE``). The token must be
a delegated user token of the configured tenant; it is mapped to the user through the administratively
bound ``EntraIdentity`` and never creates or binds a user.

A bearer token that is not an Entra token of the configured tenant is left to the next authentication
class (``None``), so Lab Mango JWTs keep working on the same views. Once a token claims to be ours, every
failure is a ``401`` (or ``403`` for a missing scope), never a fallback.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, cast
from uuid import UUID

import jwt
from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from jwt import PyJWKClient
from rest_framework import authentication, status
from rest_framework.exceptions import APIException, AuthenticationFailed, PermissionDenied
from rest_framework.request import Request

from core.users.models import EntraIdentity, User

logger = logging.getLogger(__name__)

_INVALID = "Invalid authentication token."
_MISSING_SCOPE = "The access token does not grant this API scope."


class EntraUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "unavailable"
    default_detail = "Identity provider is temporarily unavailable."


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, timeout=5, lifespan=300)


def accepted_issuers() -> frozenset[str]:
    """v2 and v1 issuers of the configured tenant (the API's accessTokenAcceptedVersion decides which)."""
    tenant = settings.AAD_TENANT_ID
    return frozenset({f"https://login.microsoftonline.com/{tenant}/v2.0", f"https://sts.windows.net/{tenant}/"})


def _claims_ours(token: str) -> bool:
    try:
        header = jwt.get_unverified_header(token)
        claims = jwt.decode(token, options={"verify_signature": False})
    except (jwt.PyJWTError, ValueError, TypeError):
        return False
    return header.get("alg") == "RS256" and claims.get("iss") in accepted_issuers()


def verify_access_token(token: str) -> dict[str, Any]:
    """Verify signature, issuer, audience, lifetime, tenant and delegated scope; return the claims."""
    try:
        signing_key = _jwks_client(settings.AAD_JWKS_URL).get_signing_key_from_jwt(token)
    except jwt.PyJWKClientConnectionError as exc:
        logger.warning("Entra JWKS connection failed")
        raise EntraUnavailable() from exc
    except jwt.PyJWTError as exc:
        logger.info("Entra access token rejected: signing key")
        raise AuthenticationFailed(_INVALID) from exc
    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=list(settings.ENTRA_API_AUDIENCES),
            leeway=60,
            options={"require": ["exp", "iat", "nbf", "iss", "aud", "tid", "oid"]},
        )
        if claims["iss"] not in accepted_issuers() or UUID(claims["tid"]) != UUID(settings.AAD_TENANT_ID):
            raise ValueError("issuer or tenant")
        UUID(claims["oid"])
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        logger.info("Entra access token rejected: claims")
        raise AuthenticationFailed(_INVALID) from exc
    # Delegated user tokens only: app-only tokens carry roles and no scp.
    if claims.get("idtyp") == "app" or not isinstance(claims.get("scp"), str):
        raise PermissionDenied(_MISSING_SCOPE)
    if settings.ENTRA_API_AUDIT_SCOPE not in claims["scp"].split():
        raise PermissionDenied(_MISSING_SCOPE)
    return claims


class EntraAccessTokenAuthentication(authentication.BaseAuthentication):
    """``Authorization: Bearer <Entra access token>`` for views that list this class explicitly."""

    # None: every method. A subset limits what the audit scope can do on a shared view.
    allowed_methods: frozenset[str] | None = None

    def authenticate(self, request: Request) -> tuple[User, dict[str, Any]] | None:
        if not getattr(settings, "ENTRA_API_ACCESS_TOKENS_ENABLED", False):
            return None
        if self.allowed_methods is not None and request.method not in self.allowed_methods:
            return None
        parts = authentication.get_authorization_header(request).split()
        if len(parts) != 2 or parts[0].lower() != b"bearer":
            return None
        try:
            token = parts[1].decode("ascii")
        except UnicodeDecodeError:
            return None
        if not _claims_ours(token):
            return None
        claims = verify_access_token(token)
        identity = (
            EntraIdentity.objects.select_related("user")
            .filter(tenant_id=UUID(claims["tid"]), object_id=UUID(claims["oid"]))
            .first()
        )
        if identity is None or not identity.user.is_active:
            logger.info("Entra access token rejected: no active bound user")
            raise AuthenticationFailed(_INVALID)
        return identity.user, claims

    def authenticate_header(self, request: Request) -> str:
        return 'Bearer realm="api"'


class EntraAccessTokenReadOnlyAuthentication(EntraAccessTokenAuthentication):
    """Accept the access token for reads only; writes on the same view need a Lab Mango JWT."""

    allowed_methods = frozenset({"GET", "HEAD", "OPTIONS"})


def with_entra_access_token(*, read_only: bool = False) -> list[type[authentication.BaseAuthentication]]:
    """Entra access-token authentication first, then the project defaults (Lab Mango JWT, session)."""
    from rest_framework.settings import api_settings

    first = EntraAccessTokenReadOnlyAuthentication if read_only else EntraAccessTokenAuthentication
    # api_settings imports the configured dotted paths, so these are classes at runtime.
    defaults = cast(list[type[authentication.BaseAuthentication]], list(api_settings.DEFAULT_AUTHENTICATION_CLASSES))
    return [first, *defaults]


class EntraAccessTokenScheme(OpenApiAuthenticationExtension):
    target_class = "core.users.features.auth.access_token.EntraAccessTokenAuthentication"
    name = "entraAccessToken"

    def get_security_definition(self, auto_schema: Any) -> dict[str, Any]:
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": (
                "Microsoft Entra delegated access token for the Lab Mango API scope "
                "(api://<client-id>/LabMango.Audit), used by the desktop audit tool."
            ),
        }


class EntraAccessTokenReadOnlyScheme(EntraAccessTokenScheme):
    target_class = "core.users.features.auth.access_token.EntraAccessTokenReadOnlyAuthentication"
    name = "entraAccessTokenRead"

    def get_security_definition(self, auto_schema: Any) -> dict[str, Any]:
        definition = super().get_security_definition(auto_schema)
        definition["description"] = (
            "Microsoft Entra delegated access token for the Lab Mango API scope "
            "(api://<client-id>/LabMango.Audit). Accepted for GET only; writes need a Lab Mango JWT."
        )
        return definition


__all__ = [
    "EntraAccessTokenAuthentication",
    "EntraAccessTokenReadOnlyAuthentication",
    "EntraUnavailable",
    "accepted_issuers",
    "verify_access_token",
    "with_entra_access_token",
]
