import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from core.users.tests.conftest import make_access_token

User = get_user_model()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_non_staff_list_returns_only_self(api_client, user, admin_user):
    token = await make_access_token(user)

    resp = await api_client.get("/api/users", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    usernames = [u["username"] for u in resp.json()["data"]]
    assert usernames == [user.username]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_staff_list_returns_all_users(api_client, admin_user, user):
    token = await make_access_token(admin_user)

    resp = await api_client.get("/api/users", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    usernames = {u["username"] for u in resp.json()["data"]}
    assert {user.username, admin_user.username} <= usernames


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_non_staff_cannot_retrieve_other_user(api_client, user, admin_user):
    token = await make_access_token(user)

    resp = await api_client.get(f"/api/users/{admin_user.pk}", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_non_staff_cannot_patch_other_user(api_client, user, admin_user):
    token = await make_access_token(user)

    resp = await api_client.patch(
        f"/api/users/{admin_user.pk}",
        data={"display_name": "Hijacked"},
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 404
    refreshed = await sync_to_async(User.objects.get)(pk=admin_user.pk)
    assert refreshed.display_name != "Hijacked"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_non_staff_can_patch_self(api_client, user):
    token = await make_access_token(user)

    resp = await api_client.patch(
        f"/api/users/{user.pk}",
        data={"display_name": "Mine"},
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["display_name"] == "Mine"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_staff_can_patch_other_user(api_client, admin_user, user):
    token = await make_access_token(admin_user)

    resp = await api_client.patch(
        f"/api/users/{user.pk}",
        data={"display_name": "By Staff"},
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["display_name"] == "By Staff"
