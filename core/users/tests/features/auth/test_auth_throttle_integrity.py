"""Problem B: auth throttles must count correctly and key on the right identity.

Production logs in through Entra SSO only (aad-login + refresh cookie), so the paths that matter are:
- a concurrent burst must not slip past the limit (non-atomic read-then-write counter);
- a client-supplied ``X-Forwarded-For`` must not give each request a fresh budget;
- colleagues behind one shared IP (office NAT / proxy) must not exhaust each other's refresh budget.

Rates are patched on DRF's shared ``DEFAULT_THROTTLE_RATES`` dict so the same test runs before and
after the fix. All tests are database-free: credential checks are mocked after the throttle.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.cache.backends.locmem import LocMemCache
from django.test import Client
from rest_framework.settings import api_settings
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import RefreshToken

from core.users.features.auth.aad_login.service import AADAuthError
from core.users.features.auth.login.service import AuthenticationError

pytestmark = pytest.mark.skip_response_contract


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


def _rates(**rates):
    return patch.dict(api_settings.DEFAULT_THROTTLE_RATES, rates)


def test_concurrent_burst_cannot_exceed_the_login_limit():
    """Before: most of 20 parallel attempts pass a 5/min limit. After: exactly 5 pass."""
    real_get = LocMemCache.get

    def get_with_network_latency(self, *args, **kwargs):
        value = real_get(self, *args, **kwargs)
        time.sleep(0.02)  # Redis round trip between reading the history and writing it back
        return value

    start = threading.Barrier(20)

    def attempt(_):
        client = Client()
        start.wait()
        return client.post(
            "/api/login",
            {"username": "alice", "password": "wrong-password"},
            content_type="application/json",
        ).status_code

    with (
        _rates(auth_login="5/min"),
        patch.object(LocMemCache, "get", get_with_network_latency),
        patch("core.users.features.auth.login.api.do_login", side_effect=AuthenticationError("invalid_credentials")),
        ThreadPoolExecutor(max_workers=20) as pool,
    ):
        statuses = list(pool.map(attempt, range(20)))

    admitted = statuses.count(401)
    assert admitted == 5, f"{admitted} of 20 attempts reached the credential check: {statuses}"
    assert statuses.count(429) == 15


def test_spoofed_forwarded_for_does_not_reset_the_sso_login_budget():
    """Before: a new X-Forwarded-For value is a new bucket, so the limit never triggers. After: 429."""
    client = Client()
    with (
        _rates(auth_login="2/min", auth_sso_login="2/min"),
        patch("core.users.features.auth.aad_login.api.aad_login", side_effect=AADAuthError("invalid")),
    ):
        statuses = [
            client.post(
                "/api/aad-login",
                {"id_token": "synthetic-token", "nonce_secret": "n" * 43},
                content_type="application/json",
                HTTP_X_FORWARDED_FOR=f"203.0.113.{i}",
            ).status_code
            for i in range(3)
        ]

    assert statuses[:2] == [401, 401]
    assert statuses[2] == 429, statuses


def _refresh_cookie_for(user_id: int) -> str:
    token = RefreshToken()
    token[jwt_settings.USER_ID_CLAIM] = str(user_id)
    return str(token)


def _refresh_as(user_id: int) -> int:
    client = Client()
    client.cookies[settings.REFRESH_TOKEN_COOKIE_NAME] = _refresh_cookie_for(user_id)
    return client.post("/api/refresh-token", content_type="application/json").status_code


def test_colleagues_behind_one_ip_do_not_share_a_refresh_budget():
    """Before: user 4 behind the same office IP gets 429 from users 1-3's refreshes. After: not throttled."""
    with (
        _rates(auth_refresh="3/min"),
        patch("core.users.features.auth.refresh_token.api.rotate_refresh", side_effect=TokenError("mocked")),
    ):
        statuses = [_refresh_as(user_id) for user_id in range(1, 7)]

    assert 429 not in statuses, statuses


def test_one_user_refreshing_too_often_is_still_throttled():
    """Per-user limit still applies (unchanged behavior)."""
    with (
        _rates(auth_refresh="3/min"),
        patch("core.users.features.auth.refresh_token.api.rotate_refresh", side_effect=TokenError("mocked")),
    ):
        statuses = [_refresh_as(42) for _ in range(4)]

    assert statuses[:3] == [401, 401, 401]
    assert statuses[3] == 429
