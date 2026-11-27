"""Redis outage during sign-in: SSO sign-in and refresh keep working and stay rate-limited.

Production signs in through Entra SSO only, and the frontend calls ``/api/aad-login`` on every page load.
If those throttles failed closed, any Redis outage would lock out everyone who reloads the page. They
now count in a process-local window while the cache is down; password login still fails closed.

All tests are database-free: the Entra and refresh services are mocked after the throttle, so a 401 means
"the request passed the throttle and reached the service".
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.cache.backends.locmem import LocMemCache
from django.test import Client
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.settings import api_settings
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import RefreshToken

from core.common.api.throttling import LocalWindowCounter, reset_local_throttle_counters
from core.users.features.auth.aad_login.service import AADAuthError

pytestmark = pytest.mark.skip_response_contract


@pytest.fixture(autouse=True)
def _clean_state():
    cache.clear()
    reset_local_throttle_counters()
    yield
    reset_local_throttle_counters()
    cache.clear()


@contextmanager
def redis_down():
    def unreachable(*args, **kwargs):
        raise RedisConnectionError("synthetic outage")

    with patch.multiple(LocMemCache, get=unreachable, set=unreachable, add=unreachable, incr=unreachable):
        yield


def _rates(**rates):
    return patch.dict(api_settings.DEFAULT_THROTTLE_RATES, rates)


def _aad_login(client: Client) -> int:
    return client.post(
        "/api/aad-login",
        {"id_token": "synthetic-token", "nonce_secret": "n" * 43},
        content_type="application/json",
    ).status_code


def _refresh_as(user_id: int) -> int:
    token = RefreshToken()
    token[jwt_settings.USER_ID_CLAIM] = str(user_id)
    client = Client()
    client.cookies[settings.REFRESH_TOKEN_COOKIE_NAME] = str(token)
    return client.post("/api/refresh-token", content_type="application/json").status_code


def test_sso_login_reaches_entra_check_while_redis_is_down():
    """Before: 503 'Authentication is temporarily unavailable'. After: the ID token is checked (401 here)."""
    with redis_down(), patch("core.users.features.auth.aad_login.api.aad_login", side_effect=AADAuthError("x")) as svc:
        status = _aad_login(Client())

    assert status == 401
    svc.assert_called_once()


def test_sso_login_is_still_limited_while_redis_is_down():
    with (
        redis_down(),
        _rates(auth_sso_login="2/min"),
        patch("core.users.features.auth.aad_login.api.aad_login", side_effect=AADAuthError("x")),
    ):
        client = Client()
        statuses = [_aad_login(client) for _ in range(3)]

    assert statuses == [401, 401, 429]


def test_refresh_reaches_rotation_while_redis_is_down():
    with (
        redis_down(),
        patch("core.users.features.auth.refresh_token.api.rotate_refresh", side_effect=TokenError("x")) as rotate,
    ):
        status = _refresh_as(7)

    assert status == 401
    rotate.assert_called_once()


def test_refresh_is_still_limited_per_user_while_redis_is_down():
    with (
        redis_down(),
        _rates(auth_refresh="3/min"),
        patch("core.users.features.auth.refresh_token.api.rotate_refresh", side_effect=TokenError("x")),
    ):
        own = [_refresh_as(42) for _ in range(4)]
        other = _refresh_as(43)

    assert own == [401, 401, 401, 429]
    assert other == 401


def test_password_login_still_fails_closed_while_redis_is_down():
    """Password login guards a guessable secret: no approximate per-worker limit, 503 as before."""
    with redis_down(), patch("core.users.features.auth.login.api.do_login") as authenticate:
        response = Client().post(
            "/api/login",
            {"username": "synthetic", "password": "synthetic-password"},
            content_type="application/json",
        )

    assert response.status_code == 503
    authenticate.assert_not_called()


def test_local_counter_restarts_each_window():
    counter = LocalWindowCounter()

    assert [counter.increment("k", window=1) for _ in range(3)] == [1, 2, 3]
    assert counter.increment("k", window=2) == 1


def test_local_counter_prunes_finished_windows_and_stays_bounded():
    counter = LocalWindowCounter(max_keys=3)
    for i in range(3):
        counter.increment(f"old:{i}", window=1)

    counter.increment("new", window=2)

    assert counter.increment("new", window=2) == 2
    assert len(counter._counts) <= 3
    for i in range(10):
        counter.increment(f"live:{i}", window=2)
    assert len(counter._counts) <= 3
