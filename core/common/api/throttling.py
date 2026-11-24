"""Technical throttle building blocks (no business imports).

Two failure policies, chosen per use:

* ``FailOpenAnonRateThrottle`` / ``FailOpenUserRateThrottle`` are the project-wide defaults. A cache
  outage must not turn every API into a 500, so they allow the request, log it, and trip the shared
  cache circuit (``core.common.cache``) so later requests skip the dead backend.
* ``AtomicRateThrottle`` is for small, security-relevant budgets (authentication). It counts with an
  atomic ``add`` + ``incr`` per fixed window, so a concurrent burst cannot slip past the limit the way
  DRF's read-then-write sliding log can. It fails closed: cache errors propagate and the exception
  handler answers 503.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from django.core.cache import cache as default_cache
from django.core.exceptions import ImproperlyConfigured
from rest_framework.settings import api_settings
from rest_framework.throttling import AnonRateThrottle, BaseThrottle, SimpleRateThrottle, UserRateThrottle

from core.common.cache import cache_circuit_open, is_cache_outage, record_cache_failure

logger = logging.getLogger(__name__)


def client_ip(request: Any) -> str:
    """Return the caller address as DRF identifies it (``REST_FRAMEWORK["NUM_PROXIES"]``-aware).

    With ``NUM_PROXIES`` unset (``DJANGO_NUM_PROXIES``), DRF keys on the whole ``X-Forwarded-For`` value,
    which a client can vary; set it to make per-IP budgets spoof-proof.
    """
    return BaseThrottle().get_ident(request) or ""


class _FailOpenMixin:
    def allow_request(self, request: Any, view: Any) -> bool:
        if cache_circuit_open():
            return True
        try:
            return super().allow_request(request, view)  # type: ignore[misc]
        except Exception as exc:
            if not is_cache_outage(exc):
                raise
            record_cache_failure()
            logger.warning(
                "Throttle cache unavailable; allowing request.",
                extra={"throttle_scope": getattr(self, "scope", None), "error_type": type(exc).__name__},
            )
            return True


class FailOpenAnonRateThrottle(_FailOpenMixin, AnonRateThrottle):
    """``AnonRateThrottle`` that allows the request when the cache backend is down."""


class FailOpenUserRateThrottle(_FailOpenMixin, UserRateThrottle):
    """``UserRateThrottle`` that allows the request when the cache backend is down."""


class AtomicRateThrottle(BaseThrottle):
    """Fixed-window counter using atomic cache ``add`` + ``incr``; fails closed.

    Subclasses set ``scope`` (a key of ``DEFAULT_THROTTLE_RATES``) and implement ``get_identity``.
    Returning ``None`` from ``get_identity`` skips this throttle for the request. Identities are hashed
    before they reach the cache key. A fixed window can admit up to twice the rate across a window
    boundary; that is acceptable for these budgets and keeps every check to two O(1) cache calls.
    """

    scope: str = ""
    cache = default_cache
    THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES

    def __init__(self) -> None:
        self._wait: float | None = None

    def get_identity(self, request: Any, view: Any) -> str | None:
        raise NotImplementedError(".get_identity() must be overridden")

    def get_rate(self) -> tuple[int, int]:
        rate = self.THROTTLE_RATES.get(self.scope)
        if not rate:
            raise ImproperlyConfigured(f"No default throttle rate set for '{self.scope}' scope")
        return SimpleRateThrottle.parse_rate(self, rate)  # type: ignore[arg-type,return-value]

    def timer(self) -> float:
        return time.time()

    def allow_request(self, request: Any, view: Any) -> bool:
        identity = self.get_identity(request, view)
        if identity is None:
            return True
        num_requests, duration = self.get_rate()
        now = self.timer()
        window = int(now // duration)
        digest = hashlib.sha256(identity.encode()).hexdigest()
        key = f"throttle:atomic:{self.scope}:{digest}:{window}"
        count = self._increment(key, timeout=duration + 1)
        if count > num_requests:
            self._wait = (window + 1) * duration - now
            return False
        return True

    def _increment(self, key: str, *, timeout: int) -> int:
        self.cache.add(key, 0, timeout=timeout)
        try:
            return int(self.cache.incr(key))
        except ValueError:
            # The key expired between add and incr; start the window again.
            self.cache.add(key, 0, timeout=timeout)
            return int(self.cache.incr(key))

    def wait(self) -> float | None:
        return self._wait


class AtomicClientIPThrottle(AtomicRateThrottle):
    """Atomic budget per trusted client address."""

    def get_identity(self, request: Any, view: Any) -> str | None:
        return f"ip:{client_ip(request)}"
