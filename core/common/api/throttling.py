"""Rate limiting with an explicit, tested policy for cache-backend outages.

DRF throttles keep their request history in the default cache (Redis in production). Stock DRF
throttles raise whatever the cache raises, so a Redis outage turns every request into a 500.

Every throttle that runs on API traffic declares what happens when its counters cannot be read
or written (``outage_policy``):

* ``"allow"`` — fail open. The request proceeds unthrottled. For general fair-use limits, where
  refusing all traffic would turn a cache outage into a full API outage while JWT verification and
  authorization (PostgreSQL) still work.
* ``"deny"`` — fail closed with ``503 service_unavailable`` and ``Retry-After``. For limits that
  protect something more valuable than availability (an expensive budget, abuse controls).

Authentication endpoints (login, AAD login, refresh, OTP) use their own limiter,
``core/users/features/auth/throttling.py`` (per IP + per account, local fallback during an outage).

While the cache circuit breaker is open (``CACHE_CIRCUIT_BREAKER_SECONDS`` after a failure in this
process), throttles apply their policy without contacting the backend, so a hung Redis costs at most
one socket timeout per window instead of one per request. Only backend errors trigger the policy;
any other exception (a bug) propagates.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle, UserRateThrottle

from core.common.cache import cache_available, is_cache_backend_error, record_cache_failure

logger = logging.getLogger(__name__)

OutagePolicy = Literal["allow", "deny"]

THROTTLE_OUTAGE_RETRY_AFTER_SECONDS = 30


class ThrottleBackendUnavailable(APIException):
    """A fail-closed throttle could not reach its counters."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The service is temporarily unavailable. Retry later."
    default_code = "service_unavailable"
    error_code = "service_unavailable"
    # DRF's exception handler turns ``wait`` into a ``Retry-After`` header.
    wait = THROTTLE_OUTAGE_RETRY_AFTER_SECONDS


class OutageAwareThrottleMixin:
    """Apply ``outage_policy`` when the throttle's cache backend fails.

    Mix in before a DRF ``SimpleRateThrottle`` subclass. ``outage_policy`` must be set explicitly;
    ``API_THROTTLE_FAIL_OPEN=False`` turns every ``"allow"`` throttle into ``"deny"`` (operations
    switch for environments that prefer refusing traffic to serving it unthrottled).
    """

    outage_policy: OutagePolicy | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        policy = cls.__dict__.get("outage_policy", getattr(cls, "outage_policy", None))
        if policy not in (None, "allow", "deny"):
            raise TypeError(f"{cls.__name__}.outage_policy must be 'allow' or 'deny', not {policy!r}")

    def effective_outage_policy(self) -> OutagePolicy:
        policy = self.outage_policy
        if policy is None:
            raise TypeError(f"{type(self).__name__} must declare outage_policy = 'allow' or 'deny'")
        if policy == "allow" and not getattr(settings, "API_THROTTLE_FAIL_OPEN", True):
            return "deny"
        return policy

    def allow_request(self, request: Any, view: Any) -> bool:
        policy = self.effective_outage_policy()
        if not cache_available():
            # Breaker open: do not wait on a backend that just failed.
            return self._on_outage(request, policy, error=None)
        try:
            return super().allow_request(request, view)  # type: ignore[misc]
        except Exception as exc:
            if not is_cache_backend_error(exc):
                raise
            record_cache_failure()
            return self._on_outage(request, policy, error=exc)

    def _on_outage(self, request: Any, policy: OutagePolicy, *, error: BaseException | None) -> bool:
        scope = getattr(self, "scope", None) or type(self).__name__
        if error is not None:
            # Logged once per breaker window: later requests skip the backend while it is open.
            logger.warning(
                "Rate-limit cache unavailable; applying outage policy.",
                extra={
                    "throttle": type(self).__name__,
                    "throttle_scope": scope,
                    "outage_policy": policy,
                    "error_type": type(error).__name__,
                    "path": getattr(request, "path", ""),
                },
            )
        if policy == "allow":
            return True
        raise ThrottleBackendUnavailable()


class ResilientAnonRateThrottle(OutageAwareThrottleMixin, AnonRateThrottle):
    """Global anonymous fair-use limit; fails open during a cache outage."""

    outage_policy: OutagePolicy = "allow"


class ResilientUserRateThrottle(OutageAwareThrottleMixin, UserRateThrottle):
    """Global per-user fair-use limit; fails open during a cache outage."""

    outage_policy: OutagePolicy = "allow"


def throttle_outage_policy(throttle_class: type[SimpleRateThrottle] | type[Any]) -> str | None:
    """The declared outage policy of ``throttle_class`` (``None`` when it declares none).

    ``"allow"`` / ``"deny"`` for ``OutageAwareThrottleMixin`` throttles; other throttles may declare
    their own handling (e.g. ``"local_fallback"`` for the authentication limiter).
    """
    policy = getattr(throttle_class, "outage_policy", None) if isinstance(throttle_class, type) else None
    return policy if isinstance(policy, str) and policy else None


__all__ = [
    "OutageAwareThrottleMixin",
    "OutagePolicy",
    "ResilientAnonRateThrottle",
    "ResilientUserRateThrottle",
    "THROTTLE_OUTAGE_RETRY_AFTER_SECONDS",
    "ThrottleBackendUnavailable",
    "throttle_outage_policy",
]
