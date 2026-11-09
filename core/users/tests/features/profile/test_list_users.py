import pytest

from core.users.tests.conftest import make_access_token


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_list_users_returns_all(api_client, user):
    token = await make_access_token(user)

    resp = await api_client.get(
        "/api/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # No page param → unpaginated → {"data": [...]}
    assert "data" in body
    usernames = [u["username"] for u in body["data"]]
    assert user.username in usernames


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_list_users_filter_by_username(api_client, user):
    token = await make_access_token(user)

    resp = await api_client.get(
        f"/api/users?username={user.username}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert all(u["username"] == user.username for u in body["data"])


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_list_users_paginated_with_page_param(api_client, user):
    token = await make_access_token(user)

    resp = await api_client.get(
        "/api/users?page=1&page_size=5",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    assert body["meta"]["pagination"]["count"] == 1
    assert body["meta"]["pagination"]["page"] == 1
    assert body["meta"]["pagination"]["page_size"] == 5


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_list_users_unauthenticated_returns_401(api_client):
    resp = await api_client.get("/api/users")
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_retrieve_user_by_id(api_client, user):
    token = await make_access_token(user)

    resp = await api_client.get(
        f"/api/users/{user.pk}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["username"] == user.username
