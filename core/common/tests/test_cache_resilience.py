"""Concurrency, outage and invalidation-hardening tests for core.common.cache and the AppAPIView read cache."""

from __future__ import annotations

import gzip
import threading
import time
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.db import transaction
from django.test import RequestFactory, override_settings
from django.utils import timezone
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.test import APIClient

import core.common.cache as cache_module
from core.common.cache import (
    acquire_cache_lock,
    bump_namespace_version,
    bump_namespace_version_on_commit,
    canonical_request_hash,
    get_namespace_version,
    namespace_version_memo,
    release_cache_lock,
    reset_cache_circuit_breaker,
    safe_cache_get,
    singleflight_fetch,
    singleflight_get_or_set,
)
from tests.factories import ComputingEquipmentFactory, UserFactory


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    reset_cache_circuit_breaker()
    cache_module._PENDING_BUMPS.clear()
    yield
    cache.clear()
    reset_cache_circuit_breaker()
    cache_module._PENDING_BUMPS.clear()


def _run_threads(count: int, target) -> None:
    threads = [threading.Thread(target=target) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


# -- Singleflight ----------------------------------------------------------------------------


def test_slow_build_runs_once_even_when_it_outlasts_the_wait_timeout():
    """A build slower than ``wait_timeout`` must not be repeated by every waiter (old behaviour: 20/20)."""
    builds = 0
    guard = threading.Lock()

    def slow_builder() -> dict[str, int]:
        nonlocal builds
        with guard:
            builds += 1
        time.sleep(0.6)
        return {"answer": 42}

    results: list[Any] = []

    def call() -> None:
        results.append(singleflight_fetch("sf:slow", slow_builder, timeout=30, lock_timeout=5, wait_timeout=0.1))

    _run_threads(12, call)

    assert builds == 1
    assert len(results) == 12
    assert all(result.value == {"answer": 42} for result in results)
    assert sorted(result.source for result in results).count("miss") == 1


def test_waiter_serves_stale_value_after_wait_timeout_while_rebuild_runs():
    cache.set("sf:stale", {"v": 1, "payload": "old"}, timeout=60)
    release_build = threading.Event()

    def builder() -> dict[str, Any]:
        release_build.wait(5)
        return {"v": 2, "payload": "new"}

    def is_fresh(entry: Any) -> bool:
        return entry.get("v") == 2

    owner_result: list[Any] = []
    owner = threading.Thread(
        target=lambda: owner_result.append(
            singleflight_fetch("sf:stale", builder, timeout=60, is_fresh=is_fresh, allow_stale=True)
        )
    )
    owner.start()
    time.sleep(0.1)  # the owner holds the build lock

    waiter = singleflight_fetch("sf:stale", builder, timeout=60, is_fresh=is_fresh, allow_stale=True, wait_timeout=0.2)
    assert waiter.source == "stale"
    assert waiter.value["payload"] == "old"

    release_build.set()
    owner.join()
    assert owner_result[0].source == "miss"
    assert cache.get("sf:stale")["payload"] == "new"


def test_waiter_takes_over_when_owner_finishes_without_caching():
    """Non-cacheable results are rebuilt by one waiter at a time, never lost in a wait loop."""
    calls = 0
    guard = threading.Lock()

    def builder() -> dict[str, bool]:
        nonlocal calls
        with guard:
            calls += 1
        time.sleep(0.05)
        return {"cacheable": False}

    results: list[Any] = []
    _run_threads(
        4,
        lambda: results.append(
            singleflight_get_or_set("sf:nocache", builder, timeout=30, cache_predicate=lambda v: v["cacheable"])
        ),
    )
    assert len(results) == 4
    assert calls == 4  # each request gets a result; none waits out the full lock lifetime


def test_lock_release_only_by_its_owner():
    first = acquire_cache_lock("lock:owner", timeout=0.2)
    assert first is not None
    time.sleep(0.3)  # first owner's lock expired
    second = acquire_cache_lock("lock:owner", timeout=5)
    assert second is not None

    assert release_cache_lock("lock:owner", first) is False
    assert cache.get("lock:owner") == second  # still held by the second owner
    assert release_cache_lock("lock:owner", second) is True
    assert cache.get("lock:owner") is None


def _redis_available() -> bool:
    try:
        import redis

        redis.Redis(host="127.0.0.1", port=6379, socket_connect_timeout=0.2).ping()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _redis_available(), reason="local Redis not available")
def test_lock_release_is_atomic_compare_and_delete_on_django_redis():
    redis_caches = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": "redis://127.0.0.1:6379/15",
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        }
    }
    with override_settings(CACHES=redis_caches):
        from django.core.cache import cache as redis_cache

        redis_cache.delete("lock:redis")
        stale_token = acquire_cache_lock("lock:redis", timeout=0.2)
        assert stale_token is not None
        time.sleep(0.35)
        live_token = acquire_cache_lock("lock:redis", timeout=5)
        assert live_token is not None
        assert release_cache_lock("lock:redis", stale_token) is False
        assert redis_cache.get("lock:redis") == live_token
        assert release_cache_lock("lock:redis", live_token) is True
        assert redis_cache.get("lock:redis") is None


# -- Circuit breaker and failed bumps -----------------------------------------------------------


@override_settings(CACHE_CIRCUIT_BREAKER_SECONDS=30)
def test_circuit_breaker_skips_cache_calls_after_a_failure():
    with patch("core.common.cache.cache.get", side_effect=RedisConnectionError("down")) as failing_get:
        assert safe_cache_get("k", "fallback") == "fallback"
        assert safe_cache_get("k", "fallback") == "fallback"
        assert get_namespace_version("ns:any") == 0
    assert failing_get.call_count == 1  # later calls fail fast without touching the backend

    reset_cache_circuit_breaker()
    cache.set("k", "value", 10)
    assert safe_cache_get("k") == "value"


@override_settings(CACHE_CIRCUIT_BREAKER_SECONDS=30)
def test_namespace_bump_ignores_open_breaker():
    before = get_namespace_version("ns:bump")
    with patch("core.common.cache.cache.get", side_effect=RedisConnectionError("down")):
        safe_cache_get("anything")  # opens the breaker
    assert bump_namespace_version("ns:bump") == before + 1


def test_failed_bump_is_queued_and_retried(monkeypatch):
    before = get_namespace_version("ns:retry")
    with patch("core.common.cache.cache.incr", side_effect=RedisConnectionError("down")):
        assert bump_namespace_version("ns:retry") == 0
    assert "ns:retry" in cache_module._PENDING_BUMPS

    monkeypatch.setattr(cache_module, "_last_pending_attempt", 0.0)
    assert get_namespace_version("ns:retry") == before + 1
    assert not cache_module._PENDING_BUMPS


def test_lost_namespace_key_restarts_above_previous_generations():
    for _ in range(3):
        bump_namespace_version("ns:evict")
    previous = get_namespace_version("ns:evict")
    cache.delete("ns:v:ns:evict")  # eviction / expiry
    assert get_namespace_version("ns:evict") > previous


def test_namespace_version_read_once_per_request_memo():
    get_namespace_version("ns:memo")
    with namespace_version_memo():
        with patch("core.common.cache.cache.get", wraps=cache.get) as spy:
            first = get_namespace_version("ns:memo")
            second = get_namespace_version("ns:memo")
        assert first == second
        assert spy.call_count == 1
        assert bump_namespace_version("ns:memo") == first + 1
        assert get_namespace_version("ns:memo") == first + 1  # a bump refreshes the memo


# -- Post-commit bump coalescing ---------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_bumps_in_one_transaction_coalesce_to_one_per_namespace():
    bumped: list[str] = []
    with patch("core.common.cache.bump_namespace_version", side_effect=bumped.append):
        with transaction.atomic():
            for _ in range(500):
                bump_namespace_version_on_commit("ns:a", "ns:b")
        assert sorted(bumped) == ["ns:a", "ns:b"]


@pytest.mark.django_db(transaction=True)
def test_coalesced_bumps_respect_savepoint_rollback():
    bumped: list[str] = []
    with patch("core.common.cache.bump_namespace_version", side_effect=bumped.append):
        with transaction.atomic():
            bump_namespace_version_on_commit("ns:outer")
            try:
                with transaction.atomic():
                    bump_namespace_version_on_commit("ns:rolled-back")
                    raise RuntimeError("abort savepoint")
            except RuntimeError:
                pass
            with transaction.atomic():
                bump_namespace_version_on_commit("ns:kept-savepoint")
            bump_namespace_version_on_commit("ns:after")
        assert sorted(bumped) == ["ns:after", "ns:kept-savepoint", "ns:outer"]

        bumped.clear()
        try:
            with transaction.atomic():
                bump_namespace_version_on_commit("ns:rolled-back-tx")
                raise RuntimeError("abort")
        except RuntimeError:
            pass
        with transaction.atomic():
            bump_namespace_version_on_commit("ns:next-tx")
        assert bumped == ["ns:next-tx"]


# -- Keys ---------------------------------------------------------------------------------------


def test_request_hash_normalizes_accept_language():
    factory = RequestFactory()
    base = canonical_request_hash(factory.get("/api/x?a=1", HTTP_ACCEPT_LANGUAGE="en-US,en;q=0.9"))
    assert canonical_request_hash(factory.get("/api/x?a=1", HTTP_ACCEPT_LANGUAGE="en-us")) == base
    junk = [
        canonical_request_hash(factory.get("/api/x?a=1", HTTP_ACCEPT_LANGUAGE=f"zz-{index},q=0.{index}"))
        for index in range(20)
    ]
    assert len(set(junk)) == 1  # unsupported languages share the default-language entry
    assert canonical_request_hash(factory.get("/api/x?a=2", HTTP_ACCEPT_LANGUAGE="en-us")) != base


def test_count_cache_skips_queries_bound_to_python_now():
    from core.common.api.pagination import _has_clock_param

    assert _has_clock_param([1, "x", timezone.now()])
    assert not _has_clock_param([1, timezone.now() - timedelta(days=3)])
    assert not _has_clock_param([])


@pytest.mark.django_db(transaction=True)
@override_settings(API_READ_CACHE_ENABLED=True, API_PAGINATION_COUNT_CACHE_TTL=60)
def test_count_cache_key_includes_parameters():
    from core.common.api.pagination import _CachedCountPaginator
    from core.labs.models import EquipmentManufacturer

    EquipmentManufacturer.objects.create(name="Alpha")
    EquipmentManufacturer.objects.create(name="Beta")
    alpha = _CachedCountPaginator(
        EquipmentManufacturer.objects.filter(name="Alpha"), 10, cache_namespace="ns:count", cache_ttl=60
    )
    none = _CachedCountPaginator(
        EquipmentManufacturer.objects.filter(name="Nope"), 10, cache_namespace="ns:count", cache_ttl=60
    )
    assert alpha.count == 1
    assert none.count == 0


# -- AppAPIView integration --------------------------------------------------------------------


class _ForbiddenSemaphore:
    async def __aenter__(self):
        raise AssertionError("cache hit must not wait for a sync-handler slot")

    async def __aexit__(self, *exc):
        return False


@pytest.mark.django_db(transaction=True)
@override_settings(API_READ_CACHE_ENABLED=True, API_AUTH_CACHE_ENABLED=True)
def test_cached_hit_bypasses_worker_semaphore_and_serves_pregzipped_body():
    admin: Any = UserFactory(username="cache-gz-admin", is_staff=True, is_superuser=True)
    for index in range(5):
        ComputingEquipmentFactory(sku=f"CACHE-GZ-{index}", name=f"Gzip Unit {index}")
    client = APIClient()
    client.force_authenticate(user=admin)
    url = "/api/labs/equipment?page=1&page_size=25"

    miss = client.get(url)
    assert miss["X-Cache"] == "MISS"
    plain = miss.content

    with patch("core.common.api.api_views._get_worker_sync_semaphore", return_value=_ForbiddenSemaphore()):
        hit = client.get(url, HTTP_ACCEPT_ENCODING="gzip")
    assert hit.status_code == 200
    assert hit["X-Cache"] == "HIT"
    assert hit["Content-Encoding"] == "gzip"
    assert hit["ETag"].startswith('W/"')
    assert gzip.decompress(hit.content) == plain

    identity = client.get(url)
    assert identity["X-Cache"] == "HIT"
    assert "Content-Encoding" not in identity
    assert identity.content == plain
    assert identity["ETag"] == miss["ETag"]

    not_modified = client.get(url, HTTP_ACCEPT_ENCODING="gzip", HTTP_IF_NONE_MATCH=hit["ETag"])
    assert not_modified.status_code == 304
    assert client.get(url, HTTP_IF_NONE_MATCH=miss["ETag"]).status_code == 304


@pytest.mark.django_db(transaction=True)
@override_settings(API_READ_CACHE_ENABLED=True)
def test_writes_still_take_the_worker_semaphore():
    admin: Any = UserFactory(username="cache-sem-admin", is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_authenticate(user=admin)
    with patch("core.common.api.api_views._get_worker_sync_semaphore", return_value=_ForbiddenSemaphore()):
        with pytest.raises(AssertionError, match="sync-handler slot"):
            client.post("/api/labs/equipment", {}, format="json")


@pytest.mark.django_db(transaction=True)
@override_settings(API_READ_CACHE_ENABLED=True, API_READ_CACHE_MAX_BYTES=64)
def test_oversized_response_is_served_but_not_cached():
    admin: Any = UserFactory(username="cache-big-admin", is_staff=True, is_superuser=True)
    ComputingEquipmentFactory(sku="CACHE-BIG-1", name="Big Unit")
    client = APIClient()
    client.force_authenticate(user=admin)
    url = "/api/labs/equipment?page=1&page_size=25"
    first = client.get(url)
    second = client.get(url)
    assert first.status_code == second.status_code == 200
    assert first["X-Cache"] == second["X-Cache"] == "BYPASS"
    assert second.json()["data"]


def _read_cache_keys() -> set[str]:
    if hasattr(cache, "keys"):  # django-redis
        return {key for key in cache.keys("api:read:*") if not key.endswith(":sf_lock")}
    return {key for key in cache._cache if ":api:read:" in key and not key.endswith(":sf_lock")}  # type: ignore[attr-defined]


@pytest.mark.django_db(transaction=True)
@override_settings(API_READ_CACHE_ENABLED=True)
def test_write_invalidates_by_overwriting_the_same_key():
    """Generations live in the entry, so a bump does not leave one orphaned key per generation."""
    admin: Any = UserFactory(username="cache-key-admin", is_staff=True, is_superuser=True)
    unit: Any = ComputingEquipmentFactory(sku="CACHE-KEY-1", name="Key Unit")
    client = APIClient()
    client.force_authenticate(user=admin)
    url = "/api/labs/equipment?page=1&page_size=25"

    assert client.get(url)["X-Cache"] == "MISS"
    keys_before = _read_cache_keys()
    unit.name = "Key Unit Renamed"
    unit.save(update_fields=["name"])
    refreshed = client.get(url)
    assert refreshed["X-Cache"] == "MISS"
    assert "Key Unit Renamed" in [row["name"] for row in refreshed.json()["data"]]
    keys_after = _read_cache_keys()
    assert keys_after == keys_before


def test_globally_cached_options_view_must_not_use_the_actor():
    from core.common.api.options import OptionsAPIView

    with pytest.raises(TypeError, match="select_uses_actor"):
        type(
            "LeakyOptionsAPIView",
            (OptionsAPIView,),
            {"__module__": __name__, "read_cache_namespace": "ns:leak", "read_cache_ttl": 30},
        )

    type(
        "UserScopedOptionsAPIView",
        (OptionsAPIView,),
        {"__module__": __name__, "read_cache_namespace": "ns:ok", "read_cache_ttl": 30, "read_cache_scope": "user"},
    )
