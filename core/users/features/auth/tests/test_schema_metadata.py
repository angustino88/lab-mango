"""Auth metadata and runtime checks on synthetic inputs, with no database or network.

Direct execution configures isolated settings without loading project environment files.
"""

if __name__ == "__main__":
    import os
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "packages/drf-api-contracts/src"))
    os.environ.pop("DJANGO_SETTINGS_MODULE", None)
    from django.conf import settings

    settings.configure(
        SECRET_KEY="synthetic-test-only",
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "rest_framework",
            "rest_framework_api_key",
            "core.common",
            "core.reference_data",
            "core.users",
            "core.agents",
            "core.routing",
            "core.labs",
            "core.support_desk",
            "core.websocket",
        ],
        AUTH_USER_MODEL="users.User",
        ALLOWED_HOSTS=["testserver"],
        DATABASES={},
        REST_FRAMEWORK={
            "DEFAULT_SCHEMA_CLASS": "config.schema.ProjectAutoSchema",
            "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
            "EXCEPTION_HANDLER": "core.common.api.exceptions.api_exception_handler",
        },
        SPECTACULAR_SETTINGS={"POSTPROCESSING_HOOKS": []},
        REFRESH_TOKEN_COOKIE_NAME="refresh_token",
    )
    import django

    django.setup()

    import pytest

    raise SystemExit(
        pytest.main(
            [
                "-c",
                str(root / "packages/drf-api-contracts/pyproject.toml"),
                "--confcutdir=" + str(Path(__file__).parent),
                "-p",
                "no:django",
                *(sys.argv[1:] or [__file__]),
                "-q",
                "--tb=short",
            ]
        )
    )

from types import SimpleNamespace

import pytest
from django.middleware.csrf import get_token
from django.urls import path
from drf_spectacular.generators import SchemaGenerator
from rest_framework.authentication import BasicAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from core.users.features.auth.aad_login.api import UserAADLoginView
from core.users.features.auth.login.api import UserLoginView
from core.users.features.auth.logout.api import UserLogoutView
from core.users.features.auth.permissions import CookieCSRFPermission
from core.users.features.auth.refresh_token.api import UserRefreshTokenView

VIEWS = [UserLoginView, UserAADLoginView, UserLogoutView, UserRefreshTokenView]


@pytest.mark.parametrize("view_class", VIEWS)
def test_explicit_public_security_preserves_contracts_and_authenticators(view_class):
    document = SchemaGenerator(patterns=[path("auth-metadata", view_class.as_view())]).get_schema(public=True)
    operation = document["paths"]["/auth-metadata"]["post"]
    assert operation["security"] == []
    assert view_class().get_authenticators() == []
    assert "CSRF" in operation["description"]
    assert "cookie" in operation["description"]
    assert set(operation["responses"]) == {
        str(status) for status in view_class.post_contract.responses.document_configured()
    }
    assert ("requestBody" in operation) == (view_class.post_contract.request is not None)
    expected = [] if view_class is UserLoginView else [CookieCSRFPermission]
    assert view_class.permission_classes == expected


def test_schema_does_not_mark_an_authenticated_subclass_public():
    class AuthenticatedRefresh(UserRefreshTokenView):
        authentication_classes = [BasicAuthentication]

    document = SchemaGenerator(patterns=[path("authenticated", AuthenticatedRefresh.as_view())]).get_schema(
        public=True
    )
    assert document["paths"]["/authenticated"]["post"]["security"] == [{"basicAuth": []}]


@pytest.mark.parametrize("view_class", [UserAADLoginView, UserLogoutView, UserRefreshTokenView])
@pytest.mark.parametrize("csrf", ["missing", "valid", "mismatch", "untrusted_origin"])
def test_cookie_csrf_is_enforced_without_authenticators(view_class, csrf):
    raw = APIRequestFactory(enforce_csrf_checks=True).post("/auth-metadata", {}, format="json")
    if csrf != "missing":
        token = get_token(raw)
        raw.COOKIES["csrftoken"] = raw.META["CSRF_COOKIE"]
        raw.META["HTTP_X_CSRFTOKEN"] = token if csrf != "mismatch" else "a" * 64
    if csrf == "untrusted_origin":
        raw.META["HTTP_ORIGIN"] = "https://untrusted.example"
    view = view_class()
    request = view.initialize_request(raw)
    if csrf == "valid":
        view.check_permissions(request)
    else:
        with pytest.raises(PermissionDenied):
            view.check_permissions(request)


def test_credential_login_has_no_cookie_csrf_requirement():
    request = Request(APIRequestFactory(enforce_csrf_checks=True).post("/login", {}, format="json"))
    UserLoginView().check_permissions(request)


def test_refresh_ignores_body_token_and_rejects_missing_cookie():
    view = UserRefreshTokenView()
    view.request = SimpleNamespace(method="POST", COOKIES={}, data={"refresh": "synthetic-not-a-token"})
    response = view.handle_post(view.request)
    assert response.status_code == 401
    assert response.data["error"]["code"] == "invalid_refresh_token"
    assert set(response.data) == {"error"}
    assert response["WWW-Authenticate"]
