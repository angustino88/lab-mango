"""Rate limiting during a cache (Redis) outage: every throttle applies its declared policy.

Scenarios:
* backend errors of every kind (redis, django-redis, socket) on read and on write;
* fail-open ("allow") and fail-closed ("deny") policies, and the API_THROTTLE_FAIL_OPEN switch;
* circuit breaker open: the backend is not contacted at all;
* normal throttling (429) is unchanged while the backend is healthy;
* non-backend exceptions are not swallowed;
* end to end with the cache mocked down and with a real django-redis client on a dead port
  (authentication endpoints: core/users/tests/features/auth/test_cache_outage.py).
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, override_settings
from django_redis.exceptions import ConnectionInterrupted
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from rest_framework.request import Request
from rest_framework.test import APIClient, force_authenticate
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle

from core.common.api.throttling import (
    OutageAwareThrottleMixin,
    ResilientAnonRateThrottle,
    ResilientUserRateThrottle,
    ThrottleBackendUnavailable,
)
from core.common.cache import cache_available, reset_cache_circuit_breaker
from core.users.features.auth.login.service import AuthenticationError

BACKEND_ERRORS = [
    RedisConnectionError("connection refused"),
    RedisTimeoutError("read timed out"),
    ConnectionInterrupted(connection=None),
    ConnectionRefusedError("refused"),
    TimeoutError("socket timeout"),
]


class _DenyThrottle(OutageAwareThrottleMixin, SimpleRateThrottle):
    scope = "test_deny"
    rate = "5/min"
    outage_policy = "deny"

    def get_cache_key(self, request: Any, view: Any) -> str:
        return self.cache_format % {"scope": self.scope, "ident": "caller"}


@pytest.fixture(autouse=True)
def _isolate():
    cache.clear()
    reset_cache_circuit_breaker()
    yield
    cache.clear()
    reset_cache_circuit_breaker()


def _user_request() -> Request:
    raw = RequestFactory().get("/api/anything")
    force_authenticate(raw, user=get_user_model()(pk=4242, username="throttle-probe"))
    request = Request(raw)
    request.user = get_user_model()(pk=4242, username="throttle-probe")
    return request


def _anon_request() -> Request:
    return Request(RequestFactory().get("/api/anything", REMOTE_ADDR="192.0.2.10"))


# -- Unit: policies ---------------------------------------------------------------------------


@pytest.mark.parametrize("error", BACKEND_ERRORS, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize(
    "throttle_class,request_factory",
    [
        (ResilientUserRateThrottle, _user_request),
        (ResilientAnonRateThrottle, _anon_request),
    ],
)
def test_fail_open_throttles_allow_on_read_failure(throttle_class, request_factory, error):
    with patch.object(throttle_class.cache, "get", side_effect=error):
        assert throttle_class().allow_request(request_factory(), view=None) is True


@pytest.mark.parametrize("error", BACKEND_ERRORS, ids=lambda e: type(e).__name__)
def test_fail_open_throttle_allows_when_recording_the_hit_fails(error):
    with patch.object(ResilientUserRateThrottle.cache, "set", side_effect=error):
        assert ResilientUserRateThrottle().allow_request(_user_request(), view=None) is True


@pytest.mark.parametrize("error", BACKEND_ERRORS, ids=lambda e: type(e).__name__)
def test_fail_closed_throttle_raises_503_on_failure(error):
    with patch.object(_DenyThrottle.cache, "get", side_effect=error):
        with pytest.raises(ThrottleBackendUnavailable) as raised:
            _DenyThrottle().allow_request(_user_request(), view=None)
    assert raised.value.status_code == 503
    assert raised.value.wait == 30


@override_settings(API_THROTTLE_FAIL_OPEN=False)
def test_fail_open_switch_turns_allow_policies_into_deny():
    with patch.object(ResilientUserRateThrottle.cache, "get", side_effect=RedisConnectionError("down")):
        with pytest.raises(ThrottleBackendUnavailable):
            ResilientUserRateThrottle().allow_request(_user_request(), view=None)


def test_programming_errors_are_not_swallowed():
    with patch.object(ResilientUserRateThrottle.cache, "get", side_effect=KeyError("bug")):
        with pytest.raises(KeyError):
            ResilientUserRateThrottle().allow_request(_user_request(), view=None)


def test_normal_rate_limiting_is_unchanged_while_cache_is_healthy():
    throttle_class = type("TwoPerMinute", (ResilientUserRateThrottle,), {"rate": "2/min"})
    request = _user_request()
    assert throttle_class().allow_request(request, None) is True
    assert throttle_class().allow_request(request, None) is True
    throttle = throttle_class()
    assert throttle.allow_request(request, None) is False
    assert 0 < throttle.wait() <= 60


def test_policy_must_be_declared_and_valid():
    with pytest.raises(TypeError, match="must be 'allow' or 'deny'"):
        type("Bad", (OutageAwareThrottleMixin, UserRateThrottle), {"outage_policy": "maybe"})
    undeclared = type("Undeclared", (OutageAwareThrottleMixin, UserRateThrottle), {})
    with pytest.raises(TypeError, match="must declare outage_policy"):
        undeclared().allow_request(_user_request(), None)


# -- Unit: circuit breaker and logging ------------------------------------------------------------


@override_settings(CACHE_CIRCUIT_BREAKER_SECONDS=30)
def test_open_breaker_skips_the_backend_and_logs_once(caplog):
    caplog.set_level(logging.WARNING, logger="core.common.api.throttling")
    with patch.object(ResilientUserRateThrottle.cache, "get", side_effect=RedisTimeoutError("timeout")) as get:
        for _ in range(5):
            assert ResilientUserRateThrottle().allow_request(_user_request(), None) is True
    assert get.call_count == 1  # later requests did not wait on the failing backend
    assert not cache_available()
    outage_logs = [r for r in caplog.records if "Rate-limit cache unavailable" in r.getMessage()]
    assert len(outage_logs) == 1
    assert outage_logs[0].outage_policy == "allow"
    assert outage_logs[0].error_type == "TimeoutError"

    with pytest.raises(ThrottleBackendUnavailable):
        _DenyThrottle().allow_request(_user_request(), None)  # deny policy also fails fast

    reset_cache_circuit_breaker()
    assert ResilientUserRateThrottle().allow_request(_user_request(), None) is True


# -- End to end ---------------------------------------------------------------------------------


def _cache_down():
    """Every default-cache call raises like an unreachable Redis (throttles and read/auth cache)."""
    error = RedisConnectionError("Error 111 connecting to redis:6379. Connection refused.")
    return patch.multiple(
        cache._connections[cache._alias].__class__,  # type: ignore[attr-defined]
        get=lambda *a, **k: (_ for _ in ()).throw(error),
        set=lambda *a, **k: (_ for _ in ()).throw(error),
        add=lambda *a, **k: (_ for _ in ()).throw(error),
        delete=lambda *a, **k: (_ for _ in ()).throw(error),
        incr=lambda *a, **k: (_ for _ in ()).throw(error),
    )


@pytest.mark.django_db
@override_settings(API_READ_CACHE_ENABLED=True, API_AUTH_CACHE_ENABLED=True)
def test_signed_in_users_and_sign_in_keep_working_during_outage():
    from tests.factories import UserFactory

    user: Any = UserFactory(username="outage-user", is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_authenticate(user=user)
    assert client.get("/api/labs/equipment").status_code == 200

    with _cache_down():
        listing = client.get("/api/labs/equipment")
        anonymous = APIClient().get("/api/labs/equipment")
        refresh = APIClient().post("/api/refresh-token", {}, format="json")
        with override_settings(AUTH_THROTTLE_OUTAGE_MODE="deny"):
            refused = APIClient().post("/api/refresh-token", {}, format="json")

    assert listing.status_code == 200
    assert listing["X-Cache"] == "BYPASS"
    assert anonymous.status_code == 401  # authentication still enforced, not a 500
    # Auth endpoints fall back to per-process limits: the request reaches the view (no refresh cookie).
    assert refresh.status_code == 401
    # "deny" mode keeps the previous fail-closed behaviour.
    assert refused.status_code == 503
    assert refused.json()["error"]["code"] == "service_unavailable"
    assert refused["Retry-After"] == "30"


@pytest.mark.django_db
@override_settings(
    API_READ_CACHE_ENABLED=True,
    API_AUTH_CACHE_ENABLED=True,
    CACHES={
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            # Nothing listens here: every call is a real connection-refused from redis-py.
            "LOCATION": "redis://127.0.0.1:6390/0",
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "SOCKET_CONNECT_TIMEOUT": 0.2,
                "SOCKET_TIMEOUT": 0.2,
            },
        }
    },
)
def test_real_django_redis_outage_end_to_end():
    from tests.factories import UserFactory

    user: Any = UserFactory(username="outage-real", is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_authenticate(user=user)

    listing = client.get("/api/labs/equipment")
    with patch("core.users.features.auth.login.api.do_login", side_effect=AuthenticationError("bad")) as do_login:
        login = APIClient().post("/api/login", {"username": "x", "password": "y"}, format="json")

    assert listing.status_code == 200
    assert login.status_code == 401  # rate limit fell back to this process; credentials were checked
    do_login.assert_called_once()


def test_finance_budget_fails_closed_with_documented_503():
    client = APIClient()
    client.force_authenticate(user=get_user_model()(pk=10101, username="finance-outage", is_superuser=True))
    source = "core.labs.features.analytics.queries.finance"
    with (
        _cache_down(),
        patch(f"{source}.aggregate_expense_cash_flow", return_value=()) as expense,
        patch(f"{source}.aggregate_procurement_cash_flow", return_value=()),
    ):
        response = client.get(
            "/api/labs/analytics/finance/summary",
            {"currency": "EUR", "start_month": "2026-01", "end_month": "2026-03"},
        )
    expense.assert_not_called()
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "service_unavailable"
    assert error["request_id"] == response["X-Request-ID"]
    assert response["Retry-After"] == "30"
