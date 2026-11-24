"""Technical caching primitives: resilient Redis/LocMem helpers, versioned namespaces,
singleflight stampede protection, and strong HTTP ETag utilities.

Strictly technical (no business app imports). Every cache operation degrades safely
(fail-open to the caller's fallback) when the cache backend is unreachable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

T = TypeVar("T")

_NS_KEY_PREFIX = "ns:v:"
_NS_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days

# Errors the cache backend raises when Redis is unreachable or too slow. django-redis re-raises the
# underlying redis/socket error when IGNORE_EXCEPTIONS is off (config/settings/production.py).
CACHE_OUTAGE_ERRORS: tuple[type[BaseException], ...] = (RedisError, TimeoutError)


def is_cache_outage(exc: BaseException) -> bool:
    """Return True when ``exc`` means the cache backend is unavailable."""
    return isinstance(exc, CACHE_OUTAGE_ERRORS)


# Process-local circuit breaker. Each failed call can block for the full socket timeout (3 s by
# default), so after one failure the fail-open readers below skip the cache for a short window
# instead of paying that timeout again on every call of every request.
_circuit: dict[str, float] = {"open_until": 0.0}


def _circuit_open_seconds() -> float:
    return float(getattr(settings, "API_CACHE_CIRCUIT_OPEN_SECONDS", 0) or 0)


def cache_circuit_open() -> bool:
    """Return True while fail-open callers should skip the cache backend."""
    return time.monotonic() < _circuit["open_until"]


def record_cache_failure() -> None:
    """Open the circuit for ``API_CACHE_CIRCUIT_OPEN_SECONDS`` (0 disables the circuit)."""
    seconds = _circuit_open_seconds()
    if seconds > 0:
        _circuit["open_until"] = time.monotonic() + seconds


def _trip_on_outage(exc: BaseException) -> None:
    if is_cache_outage(exc):
        record_cache_failure()


def reset_cache_circuit() -> None:
    """Close the circuit (tests and operational tooling)."""
    _circuit["open_until"] = 0.0


def safe_cache_get(key: str, default: Any = None) -> Any:
    """Read ``key`` from the default cache; return ``default`` on backend outage."""
    if cache_circuit_open():
        return default
    try:
        return cache.get(key, default)
    except Exception as exc:  # noqa: BLE001 - cache backend outage must not break reads
        _trip_on_outage(exc)
        logger.warning("Cache GET failed for key=%s; falling back to source.", key, exc_info=True)
        return default


def safe_cache_set(key: str, value: Any, timeout: int | float | None) -> bool:
    """Write ``key`` to the default cache; return ``False`` on backend outage."""
    if cache_circuit_open():
        return False
    try:
        cache.set(key, value, timeout=timeout)
        return True
    except Exception as exc:  # noqa: BLE001 - cache backend outage must not break reads
        _trip_on_outage(exc)
        logger.warning("Cache SET failed for key=%s.", key, exc_info=True)
        return False


def safe_cache_add(key: str, value: Any, timeout: int | float | None) -> bool:
    """Atomically set ``key`` only if absent; return ``False`` if present or on outage."""
    if cache_circuit_open():
        return False
    try:
        return bool(cache.add(key, value, timeout=timeout))
    except Exception as exc:  # noqa: BLE001
        _trip_on_outage(exc)
        logger.warning("Cache ADD failed for key=%s.", key, exc_info=True)
        return False


def safe_cache_delete(key: str) -> bool:
    """Delete ``key`` from the default cache; swallow backend outage errors.

    Deletes always try the backend (they guard correctness, not latency) but still trip the circuit.
    """
    try:
        cache.delete(key)
        return True
    except Exception as exc:  # noqa: BLE001
        _trip_on_outage(exc)
        logger.warning("Cache DELETE failed for key=%s.", key, exc_info=True)
        return False


def get_namespace_version(namespace: str) -> int:
    """Return the current integer generation for ``namespace`` (initializes to 1)."""
    if cache_circuit_open():
        return 0
    ns_key = f"{_NS_KEY_PREFIX}{namespace}"
    try:
        version = cache.get(ns_key)
        if version is None:
            cache.add(ns_key, 1, timeout=_NS_TTL_SECONDS)
            version = cache.get(ns_key)
            if version is None:
                return 1
        return int(version)
    except Exception as exc:  # noqa: BLE001
        _trip_on_outage(exc)
        logger.warning("Cache namespace read failed for namespace=%s.", namespace, exc_info=True)
        return 0


def bump_namespace_version(namespace: str) -> int:
    """Atomically advance ``namespace`` generation to invalidate all keys in that namespace.

    Invalidation always tries the backend, even while the circuit is open, so a write is never
    silently left without its bump when Redis is in fact reachable again.
    """
    ns_key = f"{_NS_KEY_PREFIX}{namespace}"
    try:
        try:
            return int(cache.incr(ns_key))
        except ValueError:
            # Key did not exist yet; initialize to 2 so it differs from default 1.
            if cache.add(ns_key, 2, timeout=_NS_TTL_SECONDS):
                return 2
            return int(cache.incr(ns_key))
    except Exception as exc:  # noqa: BLE001
        _trip_on_outage(exc)
        logger.warning("Cache namespace bump failed for namespace=%s.", namespace, exc_info=True)
        return 0


def bump_namespace_version_on_commit(*namespaces: str) -> None:
    """Schedule version bumps after the enclosing DB transaction commits.

    Safe to call both inside ``transaction.atomic()`` and in autocommit mode: Django runs
    ``on_commit`` callbacks immediately when no transaction is open, and drops them on rollback.
    """
    unique = tuple(dict.fromkeys(ns for ns in namespaces if ns))
    if not unique:
        return

    def _bump() -> None:
        for ns in unique:
            bump_namespace_version(ns)

    try:
        transaction.on_commit(_bump)
    except RuntimeError:
        # In unit tests running without database fixtures (pytest-django raises RuntimeError
        # when get_connection().ensure_connection() is called), execute the bump directly.
        _bump()


def singleflight_get_or_set(
    key: str,
    builder: Callable[[], T],
    *,
    timeout: int,
    lock_timeout: int = 5,
    wait_timeout: float = 5.0,
    poll_interval: float = 0.05,
    cache_predicate: Callable[[T], bool] | None = None,
    skip_initial_get: bool = False,
) -> tuple[T, bool]:
    """Read-through cache with singleflight lock to prevent thundering-herd stampedes.

    Returns ``(value, cache_hit)``. Only one worker builds the value on miss while
    concurrent callers wait up to ``wait_timeout`` for the populated entry. Degrades
    transparently to calling ``builder()`` directly if the cache backend is unreachable.
    """
    if cache_circuit_open():
        return builder(), False

    sentinel = object()
    if not skip_initial_get:
        cached = safe_cache_get(key, sentinel)
        if cached is not sentinel:
            return cached, True

    lock_key = f"{key}:sf_lock"
    acquired = safe_cache_add(lock_key, 1, timeout=lock_timeout)
    if acquired:
        try:
            # Double-check after acquiring lock in case another worker finished just before.
            cached = safe_cache_get(key, sentinel)
            if cached is not sentinel:
                return cached, True
            value = builder()
            if cache_predicate is None or cache_predicate(value):
                safe_cache_set(key, value, timeout=timeout)
            return value, False
        finally:
            safe_cache_delete(lock_key)

    # Another worker is computing the key; poll briefly before falling back.
    deadline = time.monotonic() + wait_timeout
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        cached = safe_cache_get(key, sentinel)
        if cached is not sentinel:
            return cached, True
        if safe_cache_get(lock_key, None) is None:
            break

    # Fallback: build directly so requests never stall indefinitely.
    value = builder()
    if cache_predicate is None or cache_predicate(value):
        safe_cache_set(key, value, timeout=timeout)
    return value, False


def compute_strong_etag(payload: Any) -> str:
    """Compute a deterministic strong SHA-256 ETag over a JSON-serializable payload."""
    rendered = json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return f'"{hashlib.sha256(rendered).hexdigest()}"'


def etag_matches(if_none_match: str | None, etag: str) -> bool:
    """Return True when ``If-None-Match`` matches ``etag`` (handles weak/multi-tag headers)."""
    if not if_none_match:
        return False
    client_etags = [tag.strip() for tag in if_none_match.split(",")]
    clean_client = [tag[2:] if tag.startswith("W/") else tag for tag in client_etags]
    clean_etag = etag.strip('"')
    return etag in client_etags or "*" in client_etags or any(tag.strip('"') == clean_etag for tag in clean_client)


def canonical_request_hash(request: Any) -> str:
    """Hash the request path, sorted query parameters, and Accept-Language header."""
    path = getattr(request, "path", "")
    query_params = getattr(request, "query_params", None)
    if query_params is None:
        query_params = getattr(request, "GET", {})
    items: list[tuple[str, str]] = []
    if hasattr(query_params, "lists"):
        for key, values in sorted(query_params.lists()):
            for val in values:
                items.append((str(key), str(val)))
    elif hasattr(query_params, "items"):
        items = sorted((str(k), str(v)) for k, v in query_params.items())

    accept_lang = ""
    headers = getattr(request, "headers", None)
    if headers is not None:
        accept_lang = str(headers.get("Accept-Language", ""))

    scheme = getattr(request, "scheme", "")
    get_host = getattr(request, "get_host", None)
    host = ""
    if callable(get_host):
        try:
            host = str(get_host())
        except Exception:  # noqa: BLE001
            host = ""

    canonical = f"{scheme}://{host}{path}?{urlencode(items)}|lang={accept_lang}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


__all__ = [
    "bump_namespace_version",
    "bump_namespace_version_on_commit",
    "canonical_request_hash",
    "compute_strong_etag",
    "etag_matches",
    "get_namespace_version",
    "safe_cache_add",
    "safe_cache_delete",
    "safe_cache_get",
    "safe_cache_set",
    "singleflight_get_or_set",
]
