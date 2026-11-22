"""Unit and integration tests for core.common.cache, AppAPIView read caching, and pagination count caching."""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.db import connection, transaction
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from rest_framework.test import APIClient

from core.common.cache import (
    bump_namespace_version,
    bump_namespace_version_on_commit,
    compute_strong_etag,
    etag_matches,
    get_namespace_version,
    safe_cache_get,
    safe_cache_set,
    singleflight_get_or_set,
)
from core.labs.models import Equipment
from tests.factories import ComputingEquipmentFactory, UserFactory


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


def test_etag_helpers_match_strong_and_weak_headers():
    etag = compute_strong_etag({"a": 1, "b": [2, 3]})
    assert etag == compute_strong_etag({"b": [2, 3], "a": 1})
    assert etag_matches(etag, etag)
    assert etag_matches(f"W/{etag}", etag)
    assert etag_matches("*", etag)
    assert not etag_matches('"different"', etag)
    assert not etag_matches(None, etag)


@pytest.mark.parametrize("error_cls", [RedisConnectionError, RedisTimeoutError])
def test_safe_cache_degrades_gracefully_on_backend_outage(error_cls):
    with patch("core.common.cache.cache.get", side_effect=error_cls("redis down")):
        assert safe_cache_get("k", default="fallback") == "fallback"
        assert get_namespace_version("labs:equipment:inventory") == 0
    with patch("core.common.cache.cache.set", side_effect=error_cls("redis down")):
        assert safe_cache_set("k", "v", timeout=10) is False


def test_singleflight_coalesces_concurrent_misses():
    build_calls = 0
    lock = threading.Lock()

    def slow_builder() -> dict[str, int]:
        nonlocal build_calls
        with lock:
            build_calls += 1
        time.sleep(0.08)
        return {"answer": 42}

    results: list[tuple[dict[str, int], bool]] = []
    threads = [
        threading.Thread(
            target=lambda: results.append(singleflight_get_or_set("sf:test:key", slow_builder, timeout=30))
        )
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 8
    assert all(val == {"answer": 42} for val, _ in results)
    assert build_calls == 1
    assert sum(1 for _, hit in results if hit) == 7


@pytest.mark.django_db(transaction=True)
def test_namespace_bump_on_commit_ignores_rolled_back_transaction():
    initial = get_namespace_version("test:tx")
    try:
        with transaction.atomic():
            bump_namespace_version_on_commit("test:tx")
            raise RuntimeError("abort")
    except RuntimeError:
        pass
    assert get_namespace_version("test:tx") == initial

    with transaction.atomic():
        bump_namespace_version_on_commit("test:tx")
    assert get_namespace_version("test:tx") == initial + 1


@pytest.mark.django_db(transaction=True)
@override_settings(API_READ_CACHE_ENABLED=True, API_AUTH_CACHE_ENABLED=True)
def test_equipment_list_read_cache_hit_etag_304_invalidation_and_outage():
    admin: Any = UserFactory(username="cache-test-admin", is_staff=True, is_superuser=True)
    unit: Any = ComputingEquipmentFactory(sku="CACHE-EQ-001", name="Cache Unit 1")
    client = APIClient()
    client.force_authenticate(user=admin)

    url = "/api/labs/equipment?page=1&page_size=25"

    # 1. Cold read: MISS, populates cache and emits ETag + Server-Timing
    first = client.get(url)
    assert first.status_code == 200
    assert first["X-Cache"] == "MISS"
    assert "ETag" in first
    assert "Server-Timing" in first
    etag = first["ETag"]

    # 2. Warm read: HIT with 0 SQL queries
    with CaptureQueriesContext(connection) as hit_queries:
        second = client.get(url)
    assert second.status_code == 200
    assert second["X-Cache"] == "HIT"
    assert second["ETag"] == etag
    assert len(hit_queries) == 0

    # 3. Conditional read with matching ETag: 304 Not Modified with 0 SQL queries
    with CaptureQueriesContext(connection) as cond_queries:
        third = client.get(url, HTTP_IF_NONE_MATCH=etag)
    assert third.status_code == 304
    assert third["ETag"] == etag
    assert third["X-Cache"] == "HIT"
    assert len(cond_queries) == 0

    # 4. Write to Equipment invalidates cache on commit -> next read is MISS with fresh data
    Equipment.objects.filter(pk=unit.pk).update(name="Updated Direct")
    unit.name = "Cache Unit Updated"
    unit.save(update_fields=["name"])

    fourth = client.get(url)
    assert fourth.status_code == 200
    assert fourth["X-Cache"] == "MISS"
    assert fourth["ETag"] != etag
    names = [row["name"] for row in fourth.json()["data"]]
    assert "Cache Unit Updated" in names

    # 5. Cache backend outage falls back cleanly to PostgreSQL with X-Cache: BYPASS
    class _BrokenCache:
        def get(self, *args, **kwargs):
            raise RedisConnectionError("redis down")

        def set(self, *args, **kwargs):
            raise RedisConnectionError("redis down")

        def add(self, *args, **kwargs):
            raise RedisConnectionError("redis down")

        def delete(self, *args, **kwargs):
            raise RedisConnectionError("redis down")

    with patch("core.common.cache.cache", _BrokenCache()):
        outage_resp = client.get(url)
    assert outage_resp.status_code == 200
    assert outage_resp["X-Cache"] == "BYPASS"


@pytest.mark.django_db(transaction=True)
@override_settings(API_READ_CACHE_ENABLED=True, API_PAGINATION_COUNT_CACHE_TTL=60)
def test_reference_data_and_facets_cached_and_invalidated():
    admin: Any = UserFactory(username="cache-ref-admin", is_staff=True, is_superuser=True)
    ComputingEquipmentFactory(sku="CACHE-REF-001", name="Ref Unit 1")
    client = APIClient()
    client.force_authenticate(user=admin)

    ref_url = "/api/labs/equipment/reference-data"
    first = client.get(ref_url)
    assert first.status_code == 200
    assert first["X-Cache"] == "MISS"

    with CaptureQueriesContext(connection) as hit_queries:
        second = client.get(ref_url)
    assert second.status_code == 200
    assert second["X-Cache"] == "HIT"
    assert len(hit_queries) == 0

    # Manual namespace bump invalidates cleanly
    bump_namespace_version("labs:equipment:refdata")
    third = client.get(ref_url)
    assert third.status_code == 200
    assert third["X-Cache"] == "MISS"
