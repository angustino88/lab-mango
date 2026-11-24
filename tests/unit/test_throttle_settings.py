"""Cross-feature regressions for global DRF throttle configuration."""

import os
import runpy
from unittest.mock import patch

import pytest
from django.core.cache import cache
from rest_framework.settings import api_settings

from config.settings import base
from core.common.api.api_views import AppAPIView
from core.common.api.throttling import FailOpenAnonRateThrottle, FailOpenUserRateThrottle
from core.users.features.auth.login.api import UserLoginView
from core.users.features.auth.throttles import AuthIPThrottle, PasswordLoginUsernameThrottle


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, {"anon": "60/min", "user": "300/min"}),
        ({"THROTTLE_ANON": "120/hour", "THROTTLE_USER": "600/hour"}, {"anon": "120/hour", "user": "600/hour"}),
    ],
)
def test_global_rates_have_defaults_and_environment_overrides(overrides, expected):
    environment = {
        "DJANGO_READ_DOT_ENV_FILE": "False",
        "DATABASE_URL": "postgres://localhost/synthetic_throttle_tests",
        "PROD_DATABASE_URL": "postgres://localhost/synthetic_throttle_tests",
        "CELERY_BROKER_URL": "memory://",
        **overrides,
    }
    with patch.dict(os.environ, environment, clear=True):
        configured = runpy.run_path(base.__file__, run_name="config.settings._throttle_test")["REST_FRAMEWORK"]

    assert configured["DEFAULT_THROTTLE_CLASSES"] == (
        "core.common.api.throttling.FailOpenAnonRateThrottle",
        "core.common.api.throttling.FailOpenUserRateThrottle",
    )
    assert configured["DEFAULT_THROTTLE_RATES"] == {
        **expected,
        "auth_login": "10/min",
        "auth_sso_login": "60/min",
        "auth_otp": "5/min",
        "auth_refresh": "30/min",
        "auth_ip": "300/min",
    }


def test_all_enabled_global_throttles_initialize():
    assert api_settings.DEFAULT_THROTTLE_CLASSES == [FailOpenAnonRateThrottle, FailOpenUserRateThrottle]
    throttles = AppAPIView().get_throttles()

    assert len(throttles) == len(api_settings.DEFAULT_THROTTLE_CLASSES)
    for throttle in throttles:
        assert throttle.rate == api_settings.DEFAULT_THROTTLE_RATES[throttle.scope]
        assert throttle.num_requests > 0
        assert throttle.duration > 0


def test_login_uses_atomic_auth_throttles_and_existing_auth_rates():
    assert UserLoginView.throttle_classes == [PasswordLoginUsernameThrottle, AuthIPThrottle]
    assert PasswordLoginUsernameThrottle.scope == "auth_login"
    for scope, variable, default in (
        ("auth_login", "THROTTLE_AUTH_LOGIN", "10/min"),
        ("auth_sso_login", "THROTTLE_AUTH_SSO_LOGIN", "60/min"),
        ("auth_otp", "THROTTLE_AUTH_OTP", "5/min"),
        ("auth_refresh", "THROTTLE_AUTH_REFRESH", "30/min"),
        ("auth_ip", "THROTTLE_AUTH_IP", "300/min"),
    ):
        assert api_settings.DEFAULT_THROTTLE_RATES[scope] == base.env(variable, default=default)


@pytest.mark.django_db
def test_authenticated_regular_endpoint_uses_global_throttles(api_client, user):
    api_client.force_authenticate(user=user)
    cache.clear()
    try:
        response = api_client.get("/api/users/me")

        assert response.status_code == 200
        assert response.data["data"]["id"] == user.pk
        assert cache.get(f"throttle_user_{user.pk}")
        assert cache.get("throttle_anon_127.0.0.1") is None
    finally:
        cache.clear()
