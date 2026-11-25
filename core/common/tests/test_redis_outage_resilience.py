"""Problem A: a Redis outage must not take down every authenticated API.

Each test simulates the production failure mode: every cache call raises the same
``redis.exceptions.ConnectionError`` that django-redis re-raises when ``IGNORE_EXCEPTIONS`` is off
(config/settings/production.py), optionally after a delay that stands in for the socket timeout.

Expected before the fix: the default throttle lets the error escape (500), and every cache read on
every request waits for the timeout again. Expected after: reads and throttling fail open, the
outage is detected once per process window, and fail-closed paths answer 503 instead of 500.
"""

import time
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.cache.backends.locmem import LocMemCache
from django.test import Client
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from core.common.api.api_views import AppAPIView
from core.common.cache import safe_cache_get

pytestmark = pytest.mark.skip_response_contract


class _AuthenticatedProbeView(AppAPIView):
    """Smallest authenticated endpoint using the project-wide default throttles."""

    def handle_get(self, request, *args, **kwargs):
        return Response({"ok": True})


class _CacheTouchingProbeView(AppAPIView):
    """Endpoint whose handler needs the cache (like agent nonces or import progress)."""

    def handle_get(self, request, *args, **kwargs):
        cache.get("probe:key")
        return Response({"ok": True})


@contextmanager
def redis_down(delay: float = 0.0):
    """Make every default-cache operation fail like an unreachable Redis."""
    calls = {"count": 0}

    def unreachable(*args, **kwargs):
        calls["count"] += 1
        if delay:
            time.sleep(delay)
        raise RedisConnectionError("synthetic outage")

    with patch.multiple(
        LocMemCache,
        get=unreachable,
        set=unreachable,
        add=unreachable,
        incr=unreachable,
        delete=unreachable,
        get_many=unreachable,
    ):
        yield calls


@pytest.fixture(autouse=True)
def _clean_cache_and_circuit(settings):
    settings.CACHE_CIRCUIT_BREAKER_SECONDS = 10
    cache.clear()
    _reset_circuit()
    yield
    _reset_circuit()
    cache.clear()


def _reset_circuit():
    from core.common.cache import reset_cache_circuit_breaker

    reset_cache_circuit_breaker()


def _get(view_cls):
    raw = APIRequestFactory().get("/probe")
    force_authenticate(raw, user=get_user_model()(pk=1, username="probe", is_active=True))
    return async_to_sync(view_cls.as_view())(raw)


def test_authenticated_api_is_served_while_redis_is_down():
    """Before: 500 internal_error from UserRateThrottle. After: 200."""
    with redis_down():
        response = _get(_AuthenticatedProbeView)

    assert response.status_code == 200, response.data
    assert response.data == {"ok": True}


def test_outage_is_detected_once_instead_of_on_every_cache_read():
    """Before: 20 reads hit the dead backend 20 times (20 x socket timeout). After: once."""
    with redis_down(delay=0.02) as calls:
        started = time.perf_counter()
        results = [safe_cache_get(f"key:{i}", "fallback") for i in range(20)]
        elapsed = time.perf_counter() - started

    assert results == ["fallback"] * 20
    assert calls["count"] == 1
    assert elapsed < 0.2


def test_requests_do_not_each_wait_for_the_redis_timeout():
    """Before: every request waits for the timeout and fails. After: only the first one waits."""
    with redis_down(delay=0.2) as calls:
        started = time.perf_counter()
        statuses = [_get(_AuthenticatedProbeView).status_code for _ in range(5)]
        elapsed = time.perf_counter() - started

    assert statuses == [200] * 5
    assert calls["count"] == 1
    assert elapsed < 0.6


def test_unhandled_cache_outage_is_503_with_retry_after_not_500():
    """Fail-closed cache users still refuse the request, but as a retryable 503."""
    with redis_down():
        response = _get(_CacheTouchingProbeView)

    assert response.status_code == 503
    assert response.data["error"]["code"] == "service_unavailable"
    assert response["Retry-After"] == "30"
    assert "synthetic outage" not in str(response.data)


def test_login_stays_fail_closed_during_outage():
    """Auth throttling keeps failing closed (owner decision), without checking credentials."""
    with (
        redis_down(),
        patch("core.users.features.auth.login.api.do_login") as authenticate,
    ):
        response = Client().post(
            "/api/login",
            {"username": "synthetic", "password": "synthetic-password"},
            content_type="application/json",
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    authenticate.assert_not_called()
