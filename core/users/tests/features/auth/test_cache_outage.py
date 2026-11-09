"""Throttle dependency failures fail closed without exposing connection details."""

from unittest.mock import patch

import pytest
from django.test import Client
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError


@pytest.mark.parametrize("error", [RedisConnectionError, RedisTimeoutError])
@pytest.mark.parametrize("path", ["/api/login", "/api/aad-login", "/api/aad-login/challenge", "/api/refresh-token"])
def test_login_cache_outage_is_503_and_never_checks_credentials(error, path):
    with (
        patch("rest_framework.throttling.ScopedRateThrottle.cache.get", side_effect=error("synthetic failure")),
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
