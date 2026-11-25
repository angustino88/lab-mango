"""Authentication rate limits: concurrent sign-ins, per-IP vs per-account, trusted proxy, refresh sessions."""

from __future__ import annotations

import threading
import uuid
from collections import Counter
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, override_settings
from rest_framework.settings import api_settings

from core.common.cache import reset_cache_circuit_breaker
from core.users.features.auth.login.service import AuthenticationError
from core.users.features.auth.throttling import AuthRateThrottle, _outage_mode, check_auth_throttle_settings

NGINX = "10.0.0.2"  # REMOTE_ADDR of every request that went through the reverse proxy


@pytest.fixture(autouse=True)
def _isolate():
    cache.clear()
    reset_cache_circuit_breaker()
    AuthRateThrottle.local_counters.clear()
    with patch("core.users.features.auth.login.api.do_login", side_effect=AuthenticationError("bad")):
        yield
    cache.clear()
    AuthRateThrottle.local_counters.clear()


def _login(username: str = "user", *, client_ip: str = "203.0.113.7", forwarded_prefix: str | None = None) -> int:
    # nginx appends the real client address to whatever the client sent ($proxy_add_x_forwarded_for).
    forwarded = f"{forwarded_prefix}, {client_ip}" if forwarded_prefix else client_ip
    response = Client(REMOTE_ADDR=NGINX, HTTP_X_FORWARDED_FOR=forwarded).post(
        "/api/login", {"username": username, "password": "guess"}, content_type="application/json"
    )
    return response.status_code


def _burst(count: int, call) -> Counter:
    codes: Counter = Counter()
    lock = threading.Lock()
    barrier = threading.Barrier(count)

    def run(index: int) -> None:
        barrier.wait()
        status = call(index)
        with lock:
            codes[status] += 1

    threads = [threading.Thread(target=run, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return codes


def test_twenty_concurrent_sign_ins_from_one_office_all_reach_the_credential_check():
    codes = _burst(20, lambda index: _login(f"employee-{index}"))
    assert codes == Counter({401: 20})  # 401 = credentials checked; no 429


def test_concurrent_guesses_on_one_account_stop_exactly_at_the_account_limit():
    codes = _burst(25, lambda index: _login("victim", client_ip=f"198.51.100.{index}"))
    assert codes == Counter({401: 10, 429: 15})  # auth_login = 10/min per account, no race


def test_per_ip_limit_applies_across_accounts():
    statuses = [_login(f"account-{index}") for index in range(61)]
    assert statuses[:60] == [401] * 60
    assert statuses[60] == 429


def test_client_supplied_forwarded_for_cannot_bypass_the_ip_limit():
    rates = {**AuthRateThrottle.THROTTLE_RATES, "auth_login_ip": "5/min"}
    with patch.object(AuthRateThrottle, "THROTTLE_RATES", rates):
        statuses = [_login(f"account-{index}", forwarded_prefix=str(uuid.uuid4())) for index in range(7)]
    assert statuses == [401] * 5 + [429] * 2


def test_throttled_response_is_standard_429_with_retry_after():
    for _ in range(10):
        _login("victim")
    response = Client(REMOTE_ADDR=NGINX, HTTP_X_FORWARDED_FOR="203.0.113.7").post(
        "/api/login", {"username": "VICTIM ", "password": "guess"}, content_type="application/json"
    )
    assert response.status_code == 429  # username is normalised: case and spaces do not reset the count
    assert response.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(response["Retry-After"]) <= 120


def test_refresh_is_limited_per_session_cookie():
    rates = {**AuthRateThrottle.THROTTLE_RATES, "auth_refresh": "2/min", "auth_refresh_ip": "100/min"}

    def refresh(token: str) -> int:
        client = Client(REMOTE_ADDR=NGINX, HTTP_X_FORWARDED_FOR="203.0.113.9")
        client.cookies["refresh_token"] = token
        return client.post("/api/refresh-token", {}, content_type="application/json").status_code

    with patch.object(AuthRateThrottle, "THROTTLE_RATES", rates):
        first_session = [refresh("session-a") for _ in range(3)]
        other_session = refresh("session-b")
    assert first_session[:2] != [429, 429]
    assert first_session[2] == 429
    assert other_session != 429


def test_settings_are_valid_at_startup():
    assert check_auth_throttle_settings() == []


@override_settings(AUTH_THROTTLE_OUTAGE_MODE="sometimes")
def test_invalid_outage_mode_fails_the_system_check():
    assert [message.id for message in check_auth_throttle_settings()] == ["users.E901"]
    with pytest.raises(ImproperlyConfigured):
        _outage_mode()


def test_missing_rate_and_untrusted_proxies_fail_the_system_check():
    rates = {key: value for key, value in api_settings.DEFAULT_THROTTLE_RATES.items() if key != "auth_login_ip"}
    with (
        patch.object(api_settings, "DEFAULT_THROTTLE_RATES", rates),
        patch.object(api_settings, "NUM_PROXIES", None),
    ):
        ids = sorted(str(message.id) for message in check_auth_throttle_settings())
    assert ids == ["users.E902", "users.W901"]
