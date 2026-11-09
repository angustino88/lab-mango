import pytest

from core.users.tests.conftest import make_access_token


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_update_user_display_name(api_client, user):
    token = await make_access_token(user)

    resp = await api_client.patch(
        f"/api/users/{user.pk}",
        data={"display_name": "New Name"},
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "New Name"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_update_user_unauthenticated_returns_401(api_client, user):
    resp = await api_client.patch(
        f"/api/users/{user.pk}",
        data={"display_name": "Anon"},
        content_type="application/json",
    )
    assert resp.status_code == 401
