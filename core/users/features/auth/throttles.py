"""Authentication throttles: atomic counters keyed on the identity each endpoint can trust.

Production signs in through Entra SSO only, so credential guessing is not the main risk; a shared
office IP exhausting one budget and concurrent bursts slipping past the limit are. Each endpoint
therefore pairs a per-identity budget with a broader per-IP backstop:

| Endpoint          | Per-identity budget                                      | Per-IP backstop |
|-------------------|----------------------------------------------------------|-----------------|
| ``/api/aad-login``| none before the ID token is verified                     | ``auth_sso_login`` |
| ``/api/refresh-token`` | ``auth_refresh`` per user, from the signature-verified cookie | ``auth_ip`` |
| ``/api/login`` (non-SSO only) | ``auth_login`` per submitted username        | ``auth_ip`` |
| ``/api/send-otp`` (non-SSO only) | ``auth_otp`` per caller                   | — |

The client address comes from ``client_ip`` (``NUM_PROXIES``-aware), never from a raw
``X-Forwarded-For`` value. All of these fail closed on a cache outage (503).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from rest_framework.exceptions import ParseError
from rest_framework_simplejwt.exceptions import TokenBackendError
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.state import token_backend

from core.common.api.throttling import AtomicClientIPThrottle, AtomicRateThrottle, client_ip


class AuthIPThrottle(AtomicClientIPThrottle):
    """Broad per-address backstop shared by the public auth endpoints."""

    scope = "auth_ip"


class SSOLoginIPThrottle(AtomicClientIPThrottle):
    """Per-address budget for Entra sign-in (no trustworthy identity before the token is verified)."""

    scope = "auth_sso_login"


class PasswordLoginUsernameThrottle(AtomicRateThrottle):
    """Per-username budget for the non-production password login."""

    scope = "auth_login"

    def get_identity(self, request: Any, view: Any) -> str | None:
        try:
            username = request.data.get("username") if hasattr(request.data, "get") else None
        except ParseError:
            username = None
        if isinstance(username, str) and username.strip():
            return f"username:{username.strip().casefold()}"
        return f"ip:{client_ip(request)}"


class RefreshUserThrottle(AtomicRateThrottle):
    """Per-user refresh budget, taken from the refresh cookie only after its signature verifies.

    An unverifiable cookie falls back to the client address, so forged tokens cannot mint fresh
    budgets or drain another user's budget. Verification is local (signature and expiry, no database).
    """

    scope = "auth_refresh"

    def get_identity(self, request: Any, view: Any) -> str | None:
        raw = request.COOKIES.get(settings.REFRESH_TOKEN_COOKIE_NAME)
        if raw:
            try:
                payload = token_backend.decode(raw, verify=True)
            except TokenBackendError:
                payload = None
            if payload and payload.get(jwt_settings.TOKEN_TYPE_CLAIM) == "refresh":
                user_id = payload.get(jwt_settings.USER_ID_CLAIM)
                if user_id is not None:
                    return f"user:{user_id}"
        return f"ip:{client_ip(request)}"


class OTPCallerThrottle(AtomicRateThrottle):
    """Per-caller OTP budget (authenticated user, otherwise the client address)."""

    scope = "auth_otp"

    def get_identity(self, request: Any, view: Any) -> str | None:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            return f"user:{user.pk}"
        return f"ip:{client_ip(request)}"
