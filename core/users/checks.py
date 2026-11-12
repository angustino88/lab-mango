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
    if not str(settings.AAD_JWKS_URL).startswith("https://login.microsoftonline.com/"):
        errors.append(Error("AAD_JWKS_URL must be a Microsoft login HTTPS URL.", id="users.E013"))
    return errors
