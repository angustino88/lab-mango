"""Password-login throttle failures fail closed without exposing connection details.

SSO sign-in and refresh count locally during an outage instead: see test_auth_throttle_outage_fallback.py.
"""

from unittest.mock import patch

import pytest
from django.test import Client
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError


@pytest.mark.parametrize("error", [RedisConnectionError, RedisTimeoutError])
def test_login_cache_outage_is_503_and_never_checks_credentials(error):
    with (
        patch("core.common.api.throttling.AtomicRateThrottle.cache.add", side_effect=error("synthetic failure")),
        patch("core.users.features.auth.login.api.do_login") as authenticate,
    ):
        response = Client().post(
            "/api/login",
            {"username": "synthetic", "password": "synthetic-password"},
            content_type="application/json",
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert response["Retry-After"] == "30"
    assert "synthetic failure" not in response.content.decode()
    authenticate.assert_not_called()
