"""Exercise the configured scoped throttle before challenge creation."""

from asgiref.sync import async_to_sync
from django.core.cache import cache
from django.urls import path
from drf_spectacular.generators import SchemaGenerator
from jsonschema import validate
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import ScopedRateThrottle

from core.users.features.auth.aad_login.api import UserAADChallengeView


def test_challenge_documents_and_returns_real_scoped_throttle_error(monkeypatch):
    def unexpected_creation():
        raise AssertionError("Throttled requests must not create challenges")

    monkeypatch.setattr("core.users.features.auth.aad_login.api.create_login_challenge", unexpected_creation)
    cache.clear()
    try:
        view = UserAADChallengeView()
        request = view.initialize_request(APIRequestFactory().post("/aad-login/challenge"))
        assert view.authentication_classes == []
        assert view.throttle_classes == [ScopedRateThrottle]
        assert view.throttle_scope == "auth_login"
        throttle = ScopedRateThrottle()
        assert throttle.allow_request(request, view)
        key = throttle.get_cache_key(request, view)
        num_requests, duration = throttle.parse_rate(throttle.get_rate())
        assert num_requests is not None and duration is not None
        cache.set(key, [throttle.timer()] * num_requests, duration)
        response = async_to_sync(UserAADChallengeView.as_view())(APIRequestFactory().post("/aad-login/challenge"))
        assert response.status_code == 429
        assert response.data["error"]["code"] == "rate_limited"
        assert int(response["Retry-After"]) > 0
        schema = SchemaGenerator(patterns=[path("aad-login/challenge", UserAADChallengeView.as_view())]).get_schema(
            public=True
        )
        operation = schema["paths"]["/aad-login/challenge"]["post"]
        assert operation["operationId"] == "aad_login_challenge_create"
        assert set(operation["responses"]) == {"200", "429", "503"}
        validate(
            response.data,
            {
                **operation["responses"]["429"]["content"]["application/json"]["schema"],
                "components": schema["components"],
            },
        )
    finally:
        cache.clear()
