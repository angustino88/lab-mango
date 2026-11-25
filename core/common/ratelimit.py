"""Race-free sliding-window rate limiting on the shared cache, with a per-process fallback.

DRF's ``SimpleRateThrottle`` reads the request history, appends, and writes it back: concurrent
requests all read the same history, so a burst passes the limit (measured: 14-20 of 20 concurrent
logins passed a 10/min limit). This limiter counts with atomic operations instead:

* ``cache.add(bucket, 0)`` creates the current window's counter only if absent (SET NX) and
  ``cache.incr(bucket)`` increments it atomically (Redis INCRBY / LocMem lock). Every request gets
  a distinct count, so no burst can exceed the limit.
* Sliding-window approximation: ``count + previous_window_count * (1 - elapsed_fraction)``. This
  avoids the 2x burst a fixed window allows across its boundary.
* Keys hash the identity (``sha256``): usernames and IPs are not stored in clear in Redis.

When the shared cache is unreachable (or the circuit breaker is open), callers can fall back to
``LocalSlidingWindow``: the same algorithm in process memory. It keeps limiting, but per worker
process, so the effective limit becomes ``limit x processes``. Its memory is bounded.
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from django.core.cache import cache

from core.common.cache import cache_available, is_cache_backend_error, record_cache_failure

_KEY_PREFIX = "rl:v1"


class RateLimitBackendUnavailable(Exception):
    """The shared counter store could not be used; the caller decides what to do."""


@dataclass(frozen=True, slots=True)
class RateLimit:
    """``limit`` requests per ``window`` seconds."""

    limit: int
    window: int

    @classmethod
    def parse(cls, rate: str) -> RateLimit:
        """Parse DRF-style rates: ``"10/min"``, ``"100/hour"``, ``"5/s"``, ``"1000/day"``."""
        count, _, period = rate.partition("/")
        seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}[period.strip()[0].lower()]
        limit = int(count)
        if limit <= 0:
            raise ValueError(f"Rate limit must be positive: {rate!r}")
        return cls(limit=limit, window=seconds)


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int  # seconds; 0 when allowed
    source: str  # "shared" or "local"


def _hash(identity: str) -> str:
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _weighted(count: int, previous: int, elapsed_fraction: float) -> float:
    return count + previous * (1.0 - elapsed_fraction)


def _retry_after(count: int, previous: int, rate: RateLimit, now: float) -> int:
    """Seconds until one more request (the retry itself) fits under the limit."""
    window = rate.window
    elapsed = now % window
    if count + 1 <= rate.limit and previous > 0:
        # Still in this window: wait until the previous window's weight decays enough.
        fraction_needed = 1.0 - (rate.limit - count - 1) / previous
        wait = fraction_needed * window - elapsed
    else:
        # This window alone is full: the next window must decay it to leave room for one request.
        wait = (window - elapsed) + window * max(0.0, 1.0 - (rate.limit - 1) / max(count, 1))
    return max(1, min(2 * window, math.ceil(wait)))


def _decide(count: int, previous: int, rate: RateLimit, now: float, source: str) -> RateLimitDecision:
    elapsed_fraction = (now % rate.window) / rate.window
    if _weighted(count, previous, elapsed_fraction) <= rate.limit:
        return RateLimitDecision(True, 0, source)
    return RateLimitDecision(False, _retry_after(count, previous, rate, now), source)


def shared_hit(scope: str, identity: str, rate: RateLimit, *, now: float | None = None) -> RateLimitDecision:
    """Count one hit against ``scope``/``identity`` on the shared cache.

    Raises ``RateLimitBackendUnavailable`` when the cache backend fails or the breaker is open.
    """
    if not cache_available():
        raise RateLimitBackendUnavailable("cache circuit breaker open")
    now = time.time() if now is None else now
    bucket = int(now // rate.window)
    base = f"{_KEY_PREFIX}:{scope}:{_hash(identity)}"
    current_key, previous_key = f"{base}:{bucket}", f"{base}:{bucket - 1}"
    ttl = 2 * rate.window + 1
    try:
        count = 0
        for _ in range(2):
            cache.add(current_key, 0, timeout=ttl)
            try:
                count = int(cache.incr(current_key))
                break
            except ValueError:
                continue  # expired between add and incr (window edge); recreate once
        else:
            raise RateLimitBackendUnavailable("counter vanished twice")
        previous = int(cache.get(previous_key) or 0)
    except RateLimitBackendUnavailable:
        raise
    except Exception as exc:
        if not is_cache_backend_error(exc):
            raise
        record_cache_failure()
        raise RateLimitBackendUnavailable(type(exc).__name__) from exc
    return _decide(count, previous, rate, now, "shared")


class LocalSlidingWindow:
    """Thread-safe in-process sliding-window counters with a bounded number of identities."""

    def __init__(self, max_keys: int = 50_000) -> None:
        self._lock = threading.Lock()
        self._max_keys = max_keys
        # key -> (bucket, count, previous_count); LRU order so the coldest identities go first.
        self._counters: OrderedDict[str, tuple[int, int, int]] = OrderedDict()

    def hit(self, scope: str, identity: str, rate: RateLimit, *, now: float | None = None) -> RateLimitDecision:
        now = time.time() if now is None else now
        bucket = int(now // rate.window)
        key = f"{scope}:{rate.window}:{_hash(identity)}"
        with self._lock:
            stored_bucket, count, previous = self._counters.pop(key, (bucket, 0, 0))
            if stored_bucket == bucket - 1:
                previous, count = count, 0
            elif stored_bucket != bucket:
                previous, count = 0, 0
            count += 1
            self._counters[key] = (bucket, count, previous)
            while len(self._counters) > self._max_keys:
                self._counters.popitem(last=False)
        return _decide(count, previous, rate, now, "local")

    def clear(self) -> None:
        with self._lock:
            self._counters.clear()

    def __len__(self) -> int:
        return len(self._counters)


__all__ = [
    "LocalSlidingWindow",
    "RateLimit",
    "RateLimitBackendUnavailable",
    "RateLimitDecision",
    "shared_hit",
]
