"""Fail closed on inconsistent production SSO settings."""

from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security)
def check_entra_configuration(app_configs, **kwargs):
    if not settings.ENTRA_SSO_ONLY:
        return []
    errors = []
    try:
        tenant = str(UUID(settings.AAD_TENANT_ID))
    except (ValueError, TypeError, AttributeError):
        return [Error("AAD_TENANT_ID must be a UUID.", id="users.E001")]
    if settings.AAD_ISSUER != f"https://login.microsoftonline.com/{tenant}/v2.0":
        errors.append(Error("Entra issuer must match the configured tenant.", id="users.E002"))
    if settings.AAD_JWKS_URL != f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys":
        errors.append(Error("Entra signing-key URL must match the configured tenant.", id="users.E003"))
    if not settings.AAD_AUDIENCE:
        errors.append(Error("AAD_AUDIENCE is required.", id="users.E004"))
    if settings.AUTHENTICATION_BACKENDS != ["core.users.backends.EntraSessionBackend"]:
        errors.append(Error("Production must use only the Entra session backend.", id="users.E005"))
    if settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] != (
        "core.users.features.auth.authentication.EntraJWTAuthentication",
    ):
        errors.append(Error("Production APIs must authenticate only Entra-issued tokens.", id="users.E008"))
    frontend = urlsplit(settings.ENTRA_FRONTEND_LOGIN_URL)
    if (frontend.netloc and frontend.scheme != "https") or settings.ENTRA_FRONTEND_LOGIN_URL.startswith("//"):
        errors.append(Error("The frontend login URL must be HTTPS or a local absolute path.", id="users.E006"))
    if not frontend.netloc and not settings.ENTRA_FRONTEND_LOGIN_URL.startswith("/"):
        errors.append(Error("The frontend login URL must be an absolute path.", id="users.E006"))
    if settings.ENTRA_BIND_BY_USERNAME and not settings.ENTRA_BIND_ALLOWED_DOMAINS:
        errors.append(
            Error("ENTRA_BIND_ALLOWED_DOMAINS is required while ENTRA_BIND_BY_USERNAME is on.", id="users.E009")
        )
    if not settings.REFRESH_TOKEN_COOKIE_SECURE:
        errors.append(Error("Production refresh cookies must be Secure.", id="users.E007"))
    return errors


@register(Tags.security)
def check_entra_access_token_configuration(app_configs, **kwargs):
    """Desktop-client access tokens (audit tool): fail at deploy, not on every scan."""
    if not getattr(settings, "ENTRA_API_ACCESS_TOKENS_ENABLED", False):
        return []
    errors = []
    audiences = [audience for audience in settings.ENTRA_API_AUDIENCES if str(audience).strip()]
    if not audiences:
        errors.append(Error("ENTRA_API_AUDIENCES is required while Entra access tokens are on.", id="users.E010"))
    scope = str(settings.ENTRA_API_AUDIT_SCOPE or "")
    if not scope.strip() or " " in scope.strip():
        errors.append(Error("ENTRA_API_AUDIT_SCOPE must be one scope name.", id="users.E011"))
    try:
        UUID(settings.AAD_TENANT_ID)
    except (ValueError, TypeError, AttributeError):
        errors.append(Error("AAD_TENANT_ID must be a UUID while Entra access tokens are on.", id="users.E012"))
    jwks_url = str(settings.AAD_JWKS_URL)
    stub_jwks = getattr(settings, "ENTRA_STUB_ISSUER_ENABLED", False) and is_loopback_http_url(jwks_url)
    if not jwks_url.startswith("https://login.microsoftonline.com/") and not stub_jwks:
        errors.append(Error("AAD_JWKS_URL must be a Microsoft login HTTPS URL.", id="users.E013"))
    return errors


def is_loopback_http_url(url: str) -> bool:
    """An ``http(s)://`` URL on 127.0.0.1 or localhost: where the local stub issuer serves its keys."""
    parts = urlsplit(url)
    return parts.scheme in {"http", "https"} and parts.hostname in {"127.0.0.1", "localhost"}


@register(Tags.security)
def check_entra_stub_issuer(app_configs, **kwargs):
    """The local stub issuer runs only in DEBUG, never with SSO-only, and only for the reserved stub tenant."""
    errors = []
    stub_tenant = _uuid_or_none(getattr(settings, "ENTRA_STUB_TENANT_ID", None))
    if getattr(settings, "ENTRA_STUB_ISSUER_ENABLED", False):
        if settings.ENTRA_SSO_ONLY or not settings.DEBUG:
            errors.append(
                Error("ENTRA_STUB_ISSUER_ENABLED is for local development (DEBUG, not SSO-only).", id="users.E014")
            )
        if stub_tenant is None or _uuid_or_none(settings.AAD_TENANT_ID) != stub_tenant:
            errors.append(
                Error("ENTRA_STUB_ISSUER_ENABLED requires AAD_TENANT_ID = ENTRA_STUB_TENANT_ID.", id="users.E014")
            )
    if settings.ENTRA_SSO_ONLY and stub_tenant is not None:
        tenants = [settings.AAD_TENANT_ID, *getattr(settings, "ROUTING_SYNC_ENTRA_TENANT_IDS", [])]
        if stub_tenant in {_uuid_or_none(tenant) for tenant in tenants}:
            errors.append(Error("The stub Entra tenant must not be configured in production.", id="users.E015"))
    return errors


def _uuid_or_none(value) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None
