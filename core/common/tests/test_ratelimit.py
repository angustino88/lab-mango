"""Sliding-window limiter: exact limits under concurrency, window maths, outage signalling, bounded memory."""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import override_settings
from redis.exceptions import ConnectionError as RedisConnectionError

from core.common.cache import reset_cache_circuit_breaker
from core.common.ratelimit import LocalSlidingWindow, RateLimit, RateLimitBackendUnavailable, shared_hit

REDIS_CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://127.0.0.1:6379/12",
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}


def _redis_available() -> bool:
    try:
        import redis

        redis.Redis(host="127.0.0.1", port=6379, socket_connect_timeout=0.2).ping()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(autouse=True)
def _isolate():
    cache.clear()
    reset_cache_circuit_breaker()
    yield
    cache.clear()
    reset_cache_circuit_breaker()


def _concurrent(count: int, call) -> list:
    results: list = []
    lock = threading.Lock()
    barrier = threading.Barrier(count)

    def run() -> None:
        barrier.wait()
        outcome = call()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=run) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        ("10/min", RateLimit(10, 60)),
        ("5/s", RateLimit(5, 1)),
        ("100/hour", RateLimit(100, 3600)),
        ("7/day", RateLimit(7, 86400)),
    ],
)
def test_rate_parsing(rate, expected):
    assert RateLimit.parse(rate) == expected


@pytest.mark.parametrize("rate", ["0/min", "-1/min", "ten/min", "10/fortnight"])
def test_invalid_rates_are_rejected(rate):
    with pytest.raises((ValueError, KeyError)):
        RateLimit.parse(rate)


def test_shared_limit_is_exact_under_concurrency_locmem():
    rate = RateLimit(10, 60)
    decisions = _concurrent(50, lambda: shared_hit("t", "burst", rate, now=1_000_020.0))
    assert sum(decision.allowed for decision in decisions) == 10
    assert all(decision.retry_after > 0 for decision in decisions if not decision.allowed)


@pytest.mark.skipif(not _redis_available(), reason="local Redis not available")
def test_shared_limit_is_exact_under_concurrency_redis():
    with override_settings(CACHES=REDIS_CACHES):
        from typing import Any

        from django.core.cache import cache

        redis_cache: Any = cache  # django-redis adds keys()

        redis_cache.clear()
        rate = RateLimit(10, 60)
        decisions = _concurrent(50, lambda: shared_hit("t", "burst-redis", rate, now=1_000_020.0))
        assert sum(decision.allowed for decision in decisions) == 10
        assert not [key for key in redis_cache.keys("rl:*") if "burst-redis" in key]  # identities are hashed
        redis_cache.clear()


def test_sliding_window_weights_the_previous_window():
    rate = RateLimit(10, 60)
    window_start = 600.0 * 60
    for _ in range(10):
        assert shared_hit("t", "slide", rate, now=window_start + 30).allowed
    # 15 s into the next window the previous 10 still weigh 7.5: only 2 more fit.
    next_window = window_start + 60 + 15
    allowed = [shared_hit("t", "slide", rate, now=next_window).allowed for _ in range(4)]
    assert allowed == [True, True, False, False]
    # Two windows later the history is gone.
    assert shared_hit("t", "slide", rate, now=window_start + 180).allowed


def test_retry_after_points_at_a_time_when_requests_fit_again():
    rate = RateLimit(5, 60)
    now = 1200.0 * 60 + 10
    for _ in range(5):
        shared_hit("t", "wait", rate, now=now)
    denied = shared_hit("t", "wait", rate, now=now)
    assert not denied.allowed
    assert 1 <= denied.retry_after <= 120
    assert shared_hit("t", "wait", rate, now=now + denied.retry_after).allowed


def test_identities_are_independent():
    rate = RateLimit(1, 60)
    assert shared_hit("t", "alice", rate, now=60.0).allowed
    assert shared_hit("t", "bob", rate, now=60.0).allowed
    assert not shared_hit("t", "alice", rate, now=60.0).allowed


def test_backend_failure_raises_with_cause():
    with patch.object(cache, "add", side_effect=RedisConnectionError("down")):
        with pytest.raises(RateLimitBackendUnavailable) as raised:
            shared_hit("t", "x", RateLimit(5, 60))
    assert isinstance(raised.value.__cause__, RedisConnectionError)


@override_settings(CACHE_CIRCUIT_BREAKER_SECONDS=30)
def test_open_breaker_skips_the_backend():
    with patch.object(cache, "add", side_effect=RedisConnectionError("down")) as add:
        for _ in range(3):
            with pytest.raises(RateLimitBackendUnavailable):
                shared_hit("t", "x", RateLimit(5, 60))
    assert add.call_count == 1


def test_programming_errors_propagate():
    with patch.object(cache, "incr", side_effect=TypeError("bug")):
        with pytest.raises(TypeError):
            shared_hit("t", "x", RateLimit(5, 60))


def test_local_limit_is_exact_under_concurrency():
    local = LocalSlidingWindow()
    decisions = _concurrent(50, lambda: local.hit("t", "burst", RateLimit(10, 60), now=1_000_020.0))
    assert sum(decision.allowed for decision in decisions) == 10
    assert all(decision.source == "local" for decision in decisions)


def test_local_window_rolls_over_with_sliding_weight():
    local = LocalSlidingWindow()
    rate = RateLimit(10, 60)
    for _ in range(10):
        assert local.hit("t", "slide", rate, now=36_030.0).allowed
    allowed = [local.hit("t", "slide", rate, now=36_075.0).allowed for _ in range(4)]
    assert allowed == [True, True, False, False]
    assert local.hit("t", "slide", rate, now=36_200.0).allowed


def test_local_memory_is_bounded():
    local = LocalSlidingWindow(max_keys=100)
    for index in range(1_000):
        local.hit("t", f"spoofed-{index}", RateLimit(5, 60), now=60.0)
    assert len(local) == 100
