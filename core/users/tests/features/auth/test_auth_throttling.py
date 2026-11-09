"""Throttling on public auth endpoints (login, OTP, refresh)."""

from unittest.mock import patch

import pytest
from django.core.cache import cache
from rest_framework.throttling import ScopedRateThrottle


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def tight_login_rate():
    """Make the login scope small enough to hit in a test without many requests."""
    with patch.object(ScopedRateThrottle, "THROTTLE_RATES", {**ScopedRateThrottle.THROTTLE_RATES, "auth_login": "2/min"}):
        yield


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_login_is_throttled_after_limit(api_client, user, tight_login_rate):
    statuses = []
    with patch("core.users.features.auth.login.service.ldap_auth", return_value=None):
        for _ in range(3):
            resp = await api_client.post(
                "/api/login",
                data={"username": user.username, "password": "wrongpassword"},
                content_type="application/json",
            )
            statuses.append(resp.status_code)

    assert statuses[:2] == [401, 401]
    assert statuses[2] == 429
