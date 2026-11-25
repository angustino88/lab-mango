"""Authentication rate limits during a cache (Redis) outage.

Default ("local"): limits count per worker process and sign-in keeps working.
"deny": refuse with 503 service_unavailable + Retry-After, before any credential check.
"""

from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import Client, override_settings
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from core.users.features.auth.login.service import AuthenticationError
from core.users.features.auth.throttling import AuthRateThrottle

PATHS = ["/api/login", "/api/aad-login", "/api/refresh-token"]


@pytest.fixture(autouse=True)
def _isolate():
    AuthRateThrottle.local_counters.clear()
    yield
    AuthRateThrottle.local_counters.clear()


@pytest.mark.parametrize("error", [RedisConnectionError, RedisTimeoutError])
@pytest.mark.parametrize("path", PATHS)
@override_settings(AUTH_THROTTLE_OUTAGE_MODE="deny")
def test_deny_mode_outage_is_503_and_never_checks_credentials(error, path):
    with (
        patch.object(cache, "add", side_effect=error("synthetic failure")),
        patch("core.users.features.auth.login.api.do_login") as authenticate,
    ):
        response = Client().post(
            path,
            {"username": "synthetic", "password": "synthetic-password"},
            content_type="application/json",
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert response["Retry-After"] == "30"
    assert "synthetic failure" not in response.content.decode()
    authenticate.assert_not_called()


@pytest.mark.parametrize("error", [RedisConnectionError, RedisTimeoutError])
def test_local_mode_outage_keeps_sign_in_working(error):
    with (
        patch.object(cache, "add", side_effect=error("synthetic failure")),
        patch("core.users.features.auth.login.api.do_login", side_effect=AuthenticationError("bad")) as authenticate,
    ):
        response = Client().post(
            "/api/login",
            {"username": "synthetic", "password": "synthetic-password"},
            content_type="application/json",
        )
    assert response.status_code == 401  # reached the credential check
    authenticate.assert_called_once()
    assert len(AuthRateThrottle.local_counters) == 2  # per-IP and per-account counted locally


def test_local_mode_outage_still_limits_per_account():
    rates = {**AuthRateThrottle.THROTTLE_RATES, "auth_login": "3/min", "auth_login_ip": "100/min"}
    statuses = []
    with (
        patch.object(AuthRateThrottle, "THROTTLE_RATES", rates),
        patch.object(cache, "add", side_effect=RedisConnectionError("down")),
        patch("core.users.features.auth.login.api.do_login", side_effect=AuthenticationError("bad")),
    ):
        for index in range(5):
            response = Client(REMOTE_ADDR=f"198.51.100.{index}").post(
                "/api/login", {"username": "victim", "password": "guess"}, content_type="application/json"
            )
            statuses.append(response.status_code)
    assert statuses == [401, 401, 401, 429, 429]
