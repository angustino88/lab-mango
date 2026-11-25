"""Rate limiting for the public authentication endpoints (login, AAD login, refresh, OTP).

Two limits per request, both counted atomically on the shared cache (``core.common.ratelimit``):

* **per client IP** (``<scope>_ip`` rate): generous, so many people behind one office NAT can sign in
  at the same time. The client IP comes from ``get_ident()``, which trusts exactly
  ``REST_FRAMEWORK["NUM_PROXIES"]`` reverse proxies in ``X-Forwarded-For``; a client cannot pick its
  identity by sending its own header.
* **per account** (``<scope>`` rate, the existing ``auth_*`` settings): strict, against password
  guessing on one account from many IPs. Applied when the view names ``throttle_account_field``.

When Redis is unreachable (``AUTH_THROTTLE_OUTAGE_MODE``):

* ``"local"`` (default): count in this worker process instead (same algorithm, bounded memory).
  Sign-in keeps working; the limits then apply per process, so the effective limit is
  ``limit x worker processes`` until Redis is back.
* ``"deny"``: refuse with ``503 service_unavailable`` and ``Retry-After: 30``.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.core import checks
from django.core.exceptions import ImproperlyConfigured
from rest_framework.exceptions import APIException
from rest_framework.settings import api_settings
from rest_framework.throttling import BaseThrottle

from core.common.ratelimit import (
    LocalSlidingWindow,
    RateLimit,
    RateLimitBackendUnavailable,
    RateLimitDecision,
    shared_hit,
)
from core.users.features.auth.api import AuthenticationServiceUnavailable

logger = logging.getLogger(__name__)

OUTAGE_MODES = ("local", "deny")
_MAX_ACCOUNT_LENGTH = 255


class AuthThrottleUnavailable(AuthenticationServiceUnavailable):
    """Raised in ``deny`` mode when the shared counters are unreachable."""

    error_code = "service_unavailable"
    wait = 30  # DRF turns ``wait`` into ``Retry-After``


def _outage_mode() -> str:
    mode = str(getattr(settings, "AUTH_THROTTLE_OUTAGE_MODE", "local")).lower()
    if mode not in OUTAGE_MODES:
        raise ImproperlyConfigured(f"AUTH_THROTTLE_OUTAGE_MODE must be one of {OUTAGE_MODES}, not {mode!r}")
    return mode


@checks.register(checks.Tags.security)
def check_auth_throttle_settings(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """Fail at startup (``manage.py check``, deploy) instead of on the first sign-in."""
    errors: list[checks.CheckMessage] = []
    try:
        _outage_mode()
    except ImproperlyConfigured as exc:
        errors.append(checks.Error(str(exc), id="users.E901"))
    rates = api_settings.DEFAULT_THROTTLE_RATES
    for scope in ("auth_login_ip", "auth_refresh_ip", "auth_otp_ip", "auth_login", "auth_refresh", "auth_otp"):
        try:
            RateLimit.parse(str(rates.get(scope) or ""))
        except (ValueError, KeyError, IndexError):
            errors.append(
                checks.Error(f"Invalid or missing throttle rate for {scope!r}: {rates.get(scope)!r}", id="users.E902")
            )
    num_proxies = api_settings.NUM_PROXIES
    if num_proxies is None or num_proxies < 0:
        errors.append(
            checks.Warning(
                "REST_FRAMEWORK NUM_PROXIES is unset: X-Forwarded-For is client-controlled and rate limits keyed by IP "
                "can be bypassed. Set TRUSTED_PROXY_COUNT to the number of reverse proxies.",
                id="users.W901",
            )
        )
    return errors


class AuthRateThrottle(BaseThrottle):
    """Per-IP and per-account limits for an authentication view.

    The view sets ``throttle_scope`` (``auth_login``, ``auth_refresh``, ``auth_otp``) and, when the
    request names an account, ``throttle_account_field`` (a request body field such as ``username``)
    or ``throttle_account_cookie`` (a cookie such as the refresh token; hashed before use).
    AAD login is limited per IP only: its Entra token is verified by signature, so there is no
    secret to guess per account.
    """

    # Declared for the throttle outage-policy architecture test.
    outage_policy = "local_fallback"
    # Read per request (patchable in tests), like DRF's SimpleRateThrottle.THROTTLE_RATES.
    THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES
    local_counters = LocalSlidingWindow()

    def __init__(self) -> None:
        self._retry_after: int | None = None

    def _rate(self, name: str) -> RateLimit:
        rate = self.THROTTLE_RATES.get(name)
        if not rate:
            raise ImproperlyConfigured(
                f"No throttle rate configured for {name!r} (REST_FRAMEWORK DEFAULT_THROTTLE_RATES)"
            )
        return RateLimit.parse(str(rate))

    @staticmethod
    def _account(request: Any, field: str | None, cookie: str | None = None) -> str | None:
        if cookie:
            token = getattr(request, "COOKIES", {}).get(cookie)
            return f"cookie:{token}" if isinstance(token, str) and token else None
        if not field:
            return None
        try:
            data = request.data
        except APIException:
            return None  # malformed body: the view reports it; the IP limit still applies
        value = data.get(field) if hasattr(data, "get") else None
        if not isinstance(value, str):
            return None
        account = value.strip().lower()[:_MAX_ACCOUNT_LENGTH]
        return account or None

    def _hit(self, scope: str, identity: str, rate: RateLimit, mode: str, request: Any) -> RateLimitDecision:
        try:
            return shared_hit(scope, identity, rate)
        except RateLimitBackendUnavailable as exc:
            if exc.__cause__ is not None:
                # A real failure (logged once per breaker window; later calls skip Redis entirely).
                logger.warning(
                    "Authentication rate-limit cache unavailable; applying outage mode.",
                    extra={
                        "throttle_scope": scope,
                        "outage_mode": mode,
                        "error_type": type(exc.__cause__).__name__,
                        "path": getattr(request, "path", ""),
                    },
                )
            if mode == "deny":
                raise AuthThrottleUnavailable() from exc
            return self.local_counters.hit(scope, identity, rate)

    def allow_request(self, request: Any, view: Any) -> bool:
        scope = getattr(view, "throttle_scope", None)
        if not scope:
            raise ImproperlyConfigured(f"{type(view).__name__} uses AuthRateThrottle without throttle_scope")
        mode = _outage_mode()
        checks = [(f"{scope}:ip", self.get_ident(request) or "unknown", self._rate(f"{scope}_ip"))]
        account = self._account(
            request,
            getattr(view, "throttle_account_field", None),
            getattr(view, "throttle_account_cookie", None),
        )
        if account is not None:
            checks.append((f"{scope}:account", account, self._rate(scope)))

        decisions = [self._hit(name, identity, rate, mode, request) for name, identity, rate in checks]
        denied = [decision for decision in decisions if not decision.allowed]
        if denied:
            self._retry_after = max(decision.retry_after for decision in denied)
            return False
        return True

    def wait(self) -> float | None:
        return self._retry_after


__all__ = ["OUTAGE_MODES", "AuthRateThrottle", "AuthThrottleUnavailable"]
