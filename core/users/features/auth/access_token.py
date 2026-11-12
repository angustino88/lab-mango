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
import time
from dataclasses import dataclass
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


class EntraIdentityNotLinked(AuthenticationFailed):
    """A valid Entra token whose subject is not linked to any Lab Mango user yet (first web sign-in links it)."""

    default_detail = "Sign in to Lab Mango in the browser once to link your Microsoft account, then retry."
    default_code = "entra_identity_not_linked"
    error_code = "entra_identity_not_linked"


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


def resolve_linked_user(claims: dict[str, Any]) -> User:
    """The active user linked to the token's ``tid``/``oid``; never creates or links one."""
    identity = (
        EntraIdentity.objects.select_related("user")
        .filter(tenant_id=UUID(claims["tid"]), object_id=UUID(claims["oid"]))
        .first()
    )
    if identity is None:
        # The signature, tenant and scope already passed, so this reveals nothing about other users.
        logger.info("Entra access token rejected: subject not linked")
        raise EntraIdentityNotLinked()
    if not identity.user.is_active:
        logger.info("Entra access token rejected: inactive user")
        raise AuthenticationFailed(_INVALID)
    return identity.user


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    name: str
    passed: bool
    detail: str


# Claims shown by the diagnostic. Never the token, the signature or the object ID.
DIAGNOSTIC_CLAIMS = ("ver", "iss", "aud", "scp", "roles", "idtyp", "tid", "exp")


def diagnose_access_token(token: str) -> tuple[list[DiagnosticCheck], dict[str, Any]]:
    """Run each check separately for operators; the last check is the real verifier, so results match it."""
    checks: list[DiagnosticCheck] = []

    def add(name: str, passed: bool, detail: str) -> bool:
        checks.append(DiagnosticCheck(name, passed, detail))
        return passed

    try:
        header = jwt.get_unverified_header(token)
        unverified = jwt.decode(token, options={"verify_signature": False})
    except (jwt.PyJWTError, ValueError, TypeError):
        add("token format", False, "not a JWT")
        return checks, {}
    shown = {name: unverified[name] for name in DIAGNOSTIC_CLAIMS if name in unverified}
    add("token format", True, "JWT")
    add("algorithm", header.get("alg") == "RS256", f"alg={header.get('alg')}")
    add("issuer", unverified.get("iss") in accepted_issuers(), f"accepted: {', '.join(sorted(accepted_issuers()))}")
    audiences = unverified.get("aud")
    audiences = [audiences] if isinstance(audiences, str) else list(audiences or [])
    add(
        "audience",
        bool(set(audiences) & set(settings.ENTRA_API_AUDIENCES)),
        f"accepted: {', '.join(settings.ENTRA_API_AUDIENCES)}",
    )
    try:
        same_tenant = UUID(str(unverified.get("tid"))) == UUID(settings.AAD_TENANT_ID)
    except ValueError:
        same_tenant = False
    add("tenant", same_tenant, "tid must equal AAD_TENANT_ID")
    exp = unverified.get("exp")
    add("not expired", isinstance(exp, int) and exp > time.time() - 60, "exp is in the future (60 s leeway)")
    delegated = unverified.get("idtyp") != "app" and isinstance(unverified.get("scp"), str)
    add("delegated user token", delegated, "needs scp; app-only tokens are refused")
    scopes = unverified.get("scp", "").split() if delegated else []
    add("scope", settings.ENTRA_API_AUDIT_SCOPE in scopes, f"needs {settings.ENTRA_API_AUDIT_SCOPE}")
    try:
        claims = verify_access_token(token)
    except APIException as exc:
        add("backend verification", False, f"{exc.status_code}: {exc.detail}")
        return checks, shown
    add("backend verification", True, "signature and all claims accepted")
    try:
        user = resolve_linked_user(claims)
    except APIException as exc:
        add("linked user", False, f"{exc.status_code}: {exc.detail}")
        return checks, shown
    add("linked user", True, f"user id {user.pk}")
    return checks, shown


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
        return resolve_linked_user(claims), claims

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
    "DiagnosticCheck",
    "EntraIdentityNotLinked",
    "EntraAccessTokenAuthentication",
    "EntraAccessTokenReadOnlyAuthentication",
    "EntraUnavailable",
    "accepted_issuers",
    "diagnose_access_token",
    "resolve_linked_user",
    "verify_access_token",
    "with_entra_access_token",
]
