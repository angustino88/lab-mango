import pytest
from asgiref.sync import sync_to_async
from rest_framework_simplejwt.tokens import RefreshToken


async def _make_refresh_token(user) -> str:
    def _create():
        return str(RefreshToken.for_user(user))
    return await sync_to_async(_create)()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_refresh_token_success(api_client, user):
    refresh = await _make_refresh_token(user)
    api_client.cookies["refresh_token"] = refresh
    resp = await api_client.post("/api/refresh-token", content_type="application/json")
    assert resp.status_code == 200
    body = resp.json()
    assert "access" in body
    # Rotation: new refresh token issued in cookie.
    assert "refresh_token" in resp.cookies


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_refresh_token_invalid_token_returns_400(api_client):
    api_client.cookies["refresh_token"] = "not-a-valid-token"
    resp = await api_client.post("/api/refresh-token", content_type="application/json")
    assert resp.status_code == 400


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_refresh_token_missing_cookie_returns_400(api_client):
    # No cookie at all — endpoint must reject the request.
    resp = await api_client.post(
        "/api/refresh-token",
        content_type="application/json",
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_refresh_token_rotation_blacklists_old_token(api_client, user):
    old_refresh = await _make_refresh_token(user)
    # Use it once — get a new pair.
    api_client.cookies["refresh_token"] = old_refresh
    await api_client.post("/api/refresh-token", content_type="application/json")
    # Re-using the old refresh token must now fail.
    api_client.cookies["refresh_token"] = old_refresh
    resp = await api_client.post("/api/refresh-token", content_type="application/json")
    assert resp.status_code == 400
