"""Technical caching primitives: resilient Redis/LocMem helpers, versioned namespaces,
singleflight stampede protection, and strong HTTP ETag utilities.

Strictly technical (no business app imports). Every cache operation degrades safely
(fail-open to the caller's fallback) when the cache backend is unreachable, and a
process-local circuit breaker turns a slow or failing backend into an immediate fallback
instead of one socket timeout per call.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar
from urllib.parse import urlencode

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

T = TypeVar("T")

_NS_KEY_PREFIX = "ns:v:"
_MISSING = object()

FetchSource = Literal["hit", "miss", "stale", "bypass"]


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class _CircuitBreaker:
    """Process-local breaker: after a backend failure, skip optional cache calls for a short window.

    Optional calls (reads, writes, locks) then return their fallback immediately instead of each
    waiting for a socket timeout. Namespace bumps never consult the breaker: invalidation is always
    attempted. After the window one call probes the backend again; another failure re-opens it.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open_until = 0.0

    @staticmethod
    def _window() -> float:
        return float(getattr(settings, "CACHE_CIRCUIT_BREAKER_SECONDS", 5) or 0)

    def allow(self) -> bool:
        return time.monotonic() >= self._open_until

    def record_failure(self) -> None:
        window = self._window()
        if window <= 0:
            return
        with self._lock:
            self._open_until = time.monotonic() + window

    def reset(self) -> None:
        with self._lock:
            self._open_until = 0.0


_BREAKER = _CircuitBreaker()


def cache_available() -> bool:
    """Whether optional cache calls are currently attempted (circuit breaker closed)."""
    return _BREAKER.allow()


def reset_cache_circuit_breaker() -> None:
    """Close the circuit breaker (tests and operational tooling)."""
    _BREAKER.reset()


# Errors the cache backend raises when Redis is unreachable or too slow. django-redis re-raises the
# underlying redis/socket error when IGNORE_EXCEPTIONS is off (config/settings/production.py).
CACHE_OUTAGE_ERRORS: tuple[type[BaseException], ...] = (RedisError, TimeoutError)
_CACHE_CLIENT_PACKAGES = frozenset({"redis", "django_redis"})


def _raised_by_cache_client(exc: BaseException) -> bool:
    tb = exc.__traceback__
    while tb is not None:
        module = tb.tb_frame.f_globals.get("__name__", "")
        if module.partition(".")[0] in _CACHE_CLIENT_PACKAGES:
            return True
        tb = tb.tb_next
    return False


def is_cache_outage(exc: BaseException) -> bool:
    """Return True when ``exc`` means the cache backend is unavailable.

    Every ``RedisError`` counts. A built-in ``TimeoutError`` counts only when the Redis client raised it:
    ``asyncio.wait_for`` and ``concurrent.futures`` raise the same type for unrelated timeouts, which must
    not be reported as a cache outage.
    """
    if isinstance(exc, RedisError):
        return True
    return isinstance(exc, TimeoutError) and _raised_by_cache_client(exc)


def record_cache_failure() -> None:
    """Open the circuit breaker after a cache outage seen outside these helpers (e.g. throttles)."""
    _BREAKER.record_failure()


def _guarded(op: str, key: str, call: Callable[[], Any], default: Any) -> Any:
    if not _BREAKER.allow():
        return default
    try:
        return call()
    except Exception:  # noqa: BLE001 - cache backend outage must not break the caller
        logger.warning("Cache %s failed for key=%s; falling back.", op, key, exc_info=True)
        _BREAKER.record_failure()
        return default


def safe_cache_get(key: str, default: Any = None) -> Any:
    """Read ``key`` from the default cache; return ``default`` on backend outage."""
    return _guarded("GET", key, lambda: cache.get(key, default), default)


def safe_cache_set(key: str, value: Any, timeout: int | float | None) -> bool:
    """Write ``key`` to the default cache; return ``False`` on backend outage."""

    def _set() -> bool:
        cache.set(key, value, timeout=timeout)
        return True

    return bool(_guarded("SET", key, _set, False))


def safe_cache_add(key: str, value: Any, timeout: int | float | None) -> bool:
    """Atomically set ``key`` only if absent; return ``False`` if present or on outage."""
    return bool(_guarded("ADD", key, lambda: bool(cache.add(key, value, timeout=timeout)), False))


def safe_cache_delete(key: str) -> bool:
    """Delete ``key`` from the default cache; swallow backend outage errors."""

    def _delete() -> bool:
        cache.delete(key)
        return True

    return bool(_guarded("DELETE", key, _delete, False))


# ---------------------------------------------------------------------------
# Versioned namespaces
# ---------------------------------------------------------------------------

# Per-request memo of namespace generations: a request reads each namespace at most once, so
# auth, roles, the read cache and the pagination count cache share one Redis round trip and
# agree on one generation. ``None`` outside a memo scope (Celery, management commands).
_NS_MEMO: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar("cache_ns_memo", default=None)

# Bumps that failed after retrying; flushed by this process on its next namespace read or bump.
_PENDING_BUMPS: set[str] = set()
_PENDING_LOCK = threading.Lock()


@contextmanager
def namespace_version_memo() -> Iterator[None]:
    """Memoize namespace generations for the enclosing request."""
    token = _NS_MEMO.set({})
    try:
        yield
    finally:
        _NS_MEMO.reset(token)


def _initial_version() -> int:
    """Seed a new or lost generation from the clock (microseconds).

    A namespace key that expires or is evicted restarts far above every generation it held before,
    so entries cached under an older generation can never be read again.
    """
    return int(time.time() * 1_000_000)


_PENDING_RETRY_INTERVAL = 1.0
_last_pending_attempt = 0.0


def _flush_pending_bumps() -> None:
    """Re-apply failed bumps, at most once per second and only while the breaker is closed."""
    global _last_pending_attempt
    if not _PENDING_BUMPS or not _BREAKER.allow():
        return
    now = time.monotonic()
    if now - _last_pending_attempt < _PENDING_RETRY_INTERVAL:
        return
    _last_pending_attempt = now
    with _PENDING_LOCK:
        pending = tuple(_PENDING_BUMPS)
        _PENDING_BUMPS.clear()
    for namespace in pending:
        bump_namespace_version(namespace)


def get_namespace_version(namespace: str) -> int:
    """Return the current generation for ``namespace``; ``0`` means "cache unavailable, bypass"."""
    memo = _NS_MEMO.get()
    if memo is not None and namespace in memo:
        return memo[namespace]
    _flush_pending_bumps()
    version = 0
    if _BREAKER.allow():
        ns_key = f"{_NS_KEY_PREFIX}{namespace}"
        try:
            raw = cache.get(ns_key)
            if raw is None:
                cache.add(ns_key, _initial_version(), timeout=None)
                raw = cache.get(ns_key)
            version = int(raw) if raw is not None else 0
        except Exception:  # noqa: BLE001
            logger.warning("Cache namespace read failed for namespace=%s.", namespace, exc_info=True)
            _BREAKER.record_failure()
            version = 0
    if memo is not None:
        memo[namespace] = version
    return version


def _bump_once(ns_key: str) -> int:
    try:
        return int(cache.incr(ns_key))
    except ValueError:
        # Missing (never created, expired or evicted): start a fresh clock-seeded generation.
        seeded = _initial_version()
        if cache.add(ns_key, seeded, timeout=None):
            return seeded
        return int(cache.incr(ns_key))


def bump_namespace_version(namespace: str) -> int:
    """Atomically advance ``namespace`` generation to invalidate all keys in that namespace.

    Always attempted (ignores the circuit breaker) and retried once. A bump that still fails is
    logged at ERROR and queued; this process re-applies it on its next namespace read or bump.
    """
    ns_key = f"{_NS_KEY_PREFIX}{namespace}"
    attempts = max(1, int(getattr(settings, "CACHE_BUMP_ATTEMPTS", 2) or 1))
    for attempt in range(attempts):
        try:
            version = _bump_once(ns_key)
        except Exception:  # noqa: BLE001
            if attempt + 1 < attempts:
                time.sleep(0.05)
                continue
            logger.error(
                "Cache namespace bump failed for namespace=%s; queued for retry. Cached reads in this "
                "namespace may be stale until the retry succeeds or their TTL expires.",
                namespace,
                exc_info=True,
            )
            with _PENDING_LOCK:
                _PENDING_BUMPS.add(namespace)
            _BREAKER.record_failure()
            memo = _NS_MEMO.get()
            if memo is not None:
                memo.pop(namespace, None)
            return 0
        memo = _NS_MEMO.get()
        if memo is not None:
            memo[namespace] = version
        _flush_pending_bumps()
        return version
    return 0  # pragma: no cover - loop always returns


@dataclass(slots=True)
class _PendingBump:
    savepoint_ids: tuple[str, ...]
    namespaces: set[str]
    callback: Callable[[], None]


def bump_namespace_version_on_commit(*namespaces: str) -> None:
    """Schedule version bumps after the enclosing DB transaction commits.

    Safe to call both inside ``transaction.atomic()`` and in autocommit mode: Django runs
    ``on_commit`` callbacks immediately when no transaction is open, and drops them on rollback.

    Bumps requested within one transaction (at the same savepoint level) coalesce into a single
    post-commit callback, so writing N rows costs one INCR per namespace instead of N.
    """
    unique = tuple(dict.fromkeys(ns for ns in namespaces if ns))
    if not unique:
        return

    def _bump_all(target: set[str] | tuple[str, ...]) -> None:
        for ns in sorted(target):
            bump_namespace_version(ns)

    try:
        connection = transaction.get_connection()
        if not connection.in_atomic_block:
            transaction.on_commit(lambda: _bump_all(unique))
            return
    except RuntimeError:
        # In unit tests running without database fixtures (pytest-django raises RuntimeError
        # when the connection is used), execute the bump directly.
        _bump_all(unique)
        return

    savepoint_ids = tuple(connection.savepoint_ids)
    pending: _PendingBump | None = getattr(connection, "_cache_pending_bump", None)
    if (
        pending is not None
        and pending.savepoint_ids == savepoint_ids
        # Still queued: Django drops callbacks on rollback (and of a rolled-back savepoint).
        and any(entry[1] is pending.callback for entry in connection.run_on_commit)
    ):
        pending.namespaces.update(unique)
        return

    target: set[str] = set(unique)
    holder: list[_PendingBump] = []

    def _callback() -> None:
        if getattr(connection, "_cache_pending_bump", None) is holder[0]:
            connection._cache_pending_bump = None
        _bump_all(target)

    new_pending = _PendingBump(savepoint_ids=savepoint_ids, namespaces=target, callback=_callback)
    holder.append(new_pending)
    connection._cache_pending_bump = new_pending
    transaction.on_commit(_callback)


# ---------------------------------------------------------------------------
# Owner-token locks
# ---------------------------------------------------------------------------

# Delete the key only if it still holds our token (no lock stealing after expiry).
_COMPARE_AND_DELETE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


def _try_lock(key: str, timeout: int | float) -> tuple[str | None, bool]:
    """Return ``(token, backend_ok)``: a token when acquired, ``backend_ok=False`` on outage."""
    if not _BREAKER.allow():
        return None, False
    token = uuid.uuid4().hex
    try:
        return (token if cache.add(key, token, timeout=timeout) else None), True
    except Exception:  # noqa: BLE001
        logger.warning("Cache lock acquire failed for key=%s.", key, exc_info=True)
        _BREAKER.record_failure()
        return None, False


def acquire_cache_lock(key: str, timeout: int | float) -> str | None:
    """Try to take ``key`` as a lock; return the owner token, ``None`` if held elsewhere or on outage."""
    return _try_lock(key, timeout)[0]


def release_cache_lock(key: str, token: str) -> bool:
    """Release ``key`` only if it is still owned by ``token``.

    Atomic compare-and-delete on django-redis; get-then-delete elsewhere (LocMem is per process).
    """
    if not _BREAKER.allow():
        return False
    try:
        client = getattr(cache, "client", None)
        if client is not None and hasattr(client, "get_client") and hasattr(client, "encode"):
            redis_client = client.get_client(write=True)
            return bool(redis_client.eval(_COMPARE_AND_DELETE_LUA, 1, client.make_key(key), client.encode(token)))
        if cache.get(key) == token:
            cache.delete(key)
            return True
        return False
    except Exception:  # noqa: BLE001
        logger.warning("Cache lock release failed for key=%s.", key, exc_info=True)
        _BREAKER.record_failure()
        return False


# ---------------------------------------------------------------------------
# Singleflight read-through
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FetchResult(Generic[T]):
    value: T
    source: FetchSource


def _lock_timeout(value: float | None) -> float:
    return float(value if value is not None else getattr(settings, "CACHE_SINGLEFLIGHT_LOCK_TIMEOUT", 30))


def _wait_timeout(value: float | None) -> float:
    return float(value if value is not None else getattr(settings, "CACHE_SINGLEFLIGHT_WAIT_TIMEOUT", 10))


def _classify(cached: Any, is_fresh: Callable[[Any], bool] | None) -> Literal["fresh", "stale", "absent"]:
    if cached is _MISSING:
        return "absent"
    if is_fresh is None or is_fresh(cached):
        return "fresh"
    return "stale"


def singleflight_fetch(
    key: str,
    builder: Callable[[], T],
    *,
    timeout: int | float,
    lock_timeout: float | None = None,
    wait_timeout: float | None = None,
    poll_interval: float = 0.05,
    max_poll_interval: float = 0.25,
    cache_predicate: Callable[[T], bool] | None = None,
    is_fresh: Callable[[Any], bool] | None = None,
    allow_stale: bool = False,
    skip_initial_get: bool = False,
) -> FetchResult[T]:
    """Read-through cache where one worker builds a missing value and others wait for it.

    * The lock carries an owner token; only its owner releases it.
    * Waiters keep waiting while a build is in progress, polling with backoff, and retry the lock
      when the owner finished without caching (or died), so at most one worker builds a key at a
      time, however slow the build. The lock lifetime (``lock_timeout``, default 30 s) bounds the
      wait: past it a waiter builds on its own, so requests never stall indefinitely.
    * ``is_fresh`` lets a cached value be present but out of date. With ``allow_stale``, a waiter
      that has waited ``wait_timeout`` (default 10 s) serves that stale value instead.
    * An unreachable backend degrades to calling ``builder()`` directly.
    """
    lock_ttl = _lock_timeout(lock_timeout)
    started = time.monotonic()
    stale_after = started + _wait_timeout(wait_timeout)
    give_up_at = started + lock_ttl
    stale: Any = _MISSING

    if not skip_initial_get:
        cached = safe_cache_get(key, _MISSING)
        state = _classify(cached, is_fresh)
        if state == "fresh":
            return FetchResult(cached, "hit")
        if state == "stale":
            stale = cached

    lock_key = f"{key}:sf_lock"
    interval = poll_interval
    while True:
        token, backend_ok = _try_lock(lock_key, lock_ttl)
        if token is not None:
            try:
                cached = safe_cache_get(key, _MISSING)
                if _classify(cached, is_fresh) == "fresh":
                    return FetchResult(cached, "hit")
                value = builder()
                if cache_predicate is None or cache_predicate(value):
                    safe_cache_set(key, value, timeout=timeout)
                return FetchResult(value, "miss")
            finally:
                release_cache_lock(lock_key, token)
        if not backend_ok:
            break
        now = time.monotonic()
        if allow_stale and stale is not _MISSING and now >= stale_after:
            return FetchResult(stale, "stale")
        if now >= give_up_at:
            break
        time.sleep(interval)
        interval = min(interval * 2, max_poll_interval)
        cached = safe_cache_get(key, _MISSING)
        state = _classify(cached, is_fresh)
        if state == "fresh":
            return FetchResult(cached, "hit")
        if state == "stale":
            stale = cached

    if allow_stale and stale is not _MISSING:
        return FetchResult(stale, "stale")
    value = builder()
    if backend_ok and (cache_predicate is None or cache_predicate(value)):
        safe_cache_set(key, value, timeout=timeout)
    return FetchResult(value, "miss" if backend_ok else "bypass")


async def asingleflight_fetch(
    key: str,
    builder: Callable[[], Awaitable[T]],
    *,
    timeout: int | float,
    lock_timeout: float | None = None,
    wait_timeout: float | None = None,
    poll_interval: float = 0.05,
    max_poll_interval: float = 0.25,
    cache_predicate: Callable[[T], bool] | None = None,
    is_fresh: Callable[[Any], bool] | None = None,
    allow_stale: bool = False,
    skip_initial_get: bool = False,
) -> FetchResult[T]:
    """Async ``singleflight_fetch``: waiters ``await`` instead of blocking a worker thread."""
    run = sync_to_async  # each cache call borrows a pool thread only for its own round trip
    get = run(safe_cache_get, thread_sensitive=False)
    lock_ttl = _lock_timeout(lock_timeout)
    started = time.monotonic()
    stale_after = started + _wait_timeout(wait_timeout)
    give_up_at = started + lock_ttl
    stale: Any = _MISSING

    if not skip_initial_get:
        cached = await get(key, _MISSING)
        state = _classify(cached, is_fresh)
        if state == "fresh":
            return FetchResult(cached, "hit")
        if state == "stale":
            stale = cached

    lock_key = f"{key}:sf_lock"
    interval = poll_interval
    while True:
        token, backend_ok = await run(_try_lock, thread_sensitive=False)(lock_key, lock_ttl)
        if token is not None:
            try:
                cached = await get(key, _MISSING)
                if _classify(cached, is_fresh) == "fresh":
                    return FetchResult(cached, "hit")
                value = await builder()
                if cache_predicate is None or cache_predicate(value):
                    await run(safe_cache_set, thread_sensitive=False)(key, value, timeout)
                return FetchResult(value, "miss")
            finally:
                await run(release_cache_lock, thread_sensitive=False)(lock_key, token)
        if not backend_ok:
            break
        now = time.monotonic()
        if allow_stale and stale is not _MISSING and now >= stale_after:
            return FetchResult(stale, "stale")
        if now >= give_up_at:
            break
        await asyncio.sleep(interval)
        interval = min(interval * 2, max_poll_interval)
        cached = await get(key, _MISSING)
        state = _classify(cached, is_fresh)
        if state == "fresh":
            return FetchResult(cached, "hit")
        if state == "stale":
            stale = cached

    if allow_stale and stale is not _MISSING:
        return FetchResult(stale, "stale")
    value = await builder()
    if backend_ok and (cache_predicate is None or cache_predicate(value)):
        await run(safe_cache_set, thread_sensitive=False)(key, value, timeout)
    return FetchResult(value, "miss" if backend_ok else "bypass")


def singleflight_get_or_set(
    key: str,
    builder: Callable[[], T],
    *,
    timeout: int,
    lock_timeout: float | None = None,
    wait_timeout: float | None = None,
    poll_interval: float = 0.05,
    cache_predicate: Callable[[T], bool] | None = None,
    skip_initial_get: bool = False,
) -> tuple[T, bool]:
    """Backward-compatible wrapper over ``singleflight_fetch`` returning ``(value, cache_hit)``."""
    result = singleflight_fetch(
        key,
        builder,
        timeout=timeout,
        lock_timeout=lock_timeout,
        wait_timeout=wait_timeout,
        poll_interval=poll_interval,
        cache_predicate=cache_predicate,
        skip_initial_get=skip_initial_get,
    )
    return result.value, result.source == "hit"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


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


def compute_body_etag(body: bytes) -> str:
    """Strong SHA-256 ETag over an already rendered response body."""
    return f'"{hashlib.sha256(body).hexdigest()}"'


def etag_matches(if_none_match: str | None, etag: str) -> bool:
    """Return True when ``If-None-Match`` matches ``etag`` (handles weak/multi-tag headers)."""
    if not if_none_match:
        return False
    client_etags = [tag.strip() for tag in if_none_match.split(",")]
    clean_client = [tag[2:] if tag.startswith("W/") else tag for tag in client_etags]
    clean_etag = etag[2:] if etag.startswith("W/") else etag
    clean_etag = clean_etag.strip('"')
    return etag in client_etags or "*" in client_etags or any(tag.strip('"') == clean_etag for tag in clean_client)


def _request_language(request: Any) -> str:
    """Normalize Accept-Language to one supported language code (bounded key space)."""
    from django.utils import translation

    django_request = getattr(request, "_request", request)
    if not hasattr(django_request, "META"):
        return ""
    try:
        return translation.get_language_from_request(django_request) or ""
    except Exception:  # noqa: BLE001
        return settings.LANGUAGE_CODE


def canonical_request_hash(request: Any) -> str:
    """Hash the host, path, sorted query parameters and negotiated language of ``request``.

    The host is part of the key because responses embed absolute URLs; ``get_host()`` is validated
    against ``ALLOWED_HOSTS``. The language is the supported code Django negotiates, not the raw
    header, so arbitrary ``Accept-Language`` values cannot fragment the cache.
    """
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

    scheme = getattr(request, "scheme", "")
    get_host = getattr(request, "get_host", None)
    host = ""
    if callable(get_host):
        try:
            host = str(get_host()).lower()
        except Exception:  # noqa: BLE001
            host = ""

    canonical = f"{scheme}://{host}{path}?{urlencode(items)}|lang={_request_language(request)}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


__all__ = [
    "CACHE_OUTAGE_ERRORS",
    "FetchResult",
    "acquire_cache_lock",
    "asingleflight_fetch",
    "bump_namespace_version",
    "bump_namespace_version_on_commit",
    "cache_available",
    "canonical_request_hash",
    "compute_body_etag",
    "compute_strong_etag",
    "etag_matches",
    "get_namespace_version",
    "is_cache_outage",
    "namespace_version_memo",
    "record_cache_failure",
    "release_cache_lock",
    "reset_cache_circuit_breaker",
    "safe_cache_add",
    "safe_cache_delete",
    "safe_cache_get",
    "safe_cache_set",
    "singleflight_fetch",
    "singleflight_get_or_set",
]
