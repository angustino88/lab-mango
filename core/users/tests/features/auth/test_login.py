from unittest.mock import patch

import pytest


def _mock_ldap_auth(user):
    """Context manager that patches ldap_auth to return the given user."""
    return patch(
        "core.users.features.auth.login.service.ldap_auth",
        return_value=user,
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_login_success(api_client, admin_user):
    with _mock_ldap_auth(admin_user):
        resp = await api_client.post(
            "/api/login",
            data={"username": admin_user.username, "password": "adminlab"},
            content_type="application/json",
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "access" in body["data"]
    # Refresh token is set as HttpOnly cookie, never in the body.
    assert "refresh" not in body["data"]
    assert "refresh_token" in resp.cookies
    assert body["data"]["username"] == admin_user.username
    assert body["data"]["is_active"] is True


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_login_non_superuser_rejected_returns_401(api_client, user):
    # Non-superadmin is rejected because password login is restricted to super admins
    with _mock_ldap_auth(user):
        resp = await api_client.post(
            "/api/login",
            data={"username": user.username, "password": "testpass123"},
            content_type="application/json",
        )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"
    assert resp["WWW-Authenticate"] == 'Bearer realm="api"'


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_login_inactive_user_returns_401(api_client, inactive_user):
    # Inactive user is rejected before ldap_auth is called — no mock needed
    resp = await api_client.post(
        "/api/login",
        data={"username": inactive_user.username, "password": "testpass123"},
        content_type="application/json",
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"
    assert resp["WWW-Authenticate"] == 'Bearer realm="api"'


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_login_wrong_password_returns_401(api_client, admin_user):
    with patch("core.users.features.auth.login.service.ldap_auth", return_value=None):
        resp = await api_client.post(
            "/api/login",
            data={"username": admin_user.username, "password": "wrongpassword"},
            content_type="application/json",
        )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_login_nonexistent_user_returns_401(api_client):
    # Non-existent user is rejected before ldap_auth is called — no mock needed
    resp = await api_client.post(
        "/api/login",
        data={"username": "nobody", "password": "pass"},
        content_type="application/json",
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_login_missing_fields_returns_422(api_client):
    resp = await api_client.post(
        "/api/login",
        data={},
        content_type="application/json",
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_login_access_token_is_string(api_client, admin_user):
    with _mock_ldap_auth(admin_user):
        resp = await api_client.post(
            "/api/login",
            data={"username": admin_user.username, "password": "adminlab"},
            content_type="application/json",
        )
    assert resp.status_code == 200
    body = resp.json()
    # Old backend had bug B1: access_token was a tuple due to trailing comma.
    # Access token is a plain string in the body; refresh token is in the cookie.
    assert isinstance(body["data"]["access"], str)
    assert isinstance(resp.cookies["refresh_token"].value, str)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_login_staff_non_superuser_rejected_returns_401(api_client):
    from core.users.models import User

    staff_user = await User.objects.acreate_user(
        username="staffonly",
        password="staffpassword123",
        is_staff=True,
        is_superuser=False,
    )
    with _mock_ldap_auth(staff_user):
        resp = await api_client.post(
            "/api/login",
            data={"username": "staffonly", "password": "staffpassword123"},
            content_type="application/json",
        )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_login_custom_superuser_authenticates_with_local_password(api_client):
    from core.users.models import User

    # Superuser with custom username (not in LDAP_AUTH_WHITELIST)
    await User.objects.acreate_superuser(
        username="custom_dev_admin",
        email="devadmin@example.com",
        password="securelocalpass123",
    )
    resp = await api_client.post(
        "/api/login",
        data={"username": "custom_dev_admin", "password": "securelocalpass123"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["username"] == "custom_dev_admin"
    assert "access" in body["data"]
    assert "refresh_token" in resp.cookies


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_login_entra_sso_only_rejects_login(api_client, admin_user, settings):
    settings.ENTRA_SSO_ONLY = True
    resp = await api_client.post(
        "/api/login",
        data={"username": admin_user.username, "password": "adminlab"},
        content_type="application/json",
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"
