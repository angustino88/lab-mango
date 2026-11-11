import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth.models import Group

from core.users.models import URSGroup
from core.users.tests.conftest import make_access_token


def _grant_role(user, role: str, urs_group_id: int) -> None:
    group = Group.objects.create(name=f"role-{role}-{user.username}")
    URSGroup.objects.create(group=group, urs_group_id=urs_group_id, labs_role=role)
    user.groups.add(group)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_list_groups_returns_group_with_users(api_client, user, group):
    await sync_to_async(user.groups.add)(group)
    await sync_to_async(_grant_role)(user, "admin", 97001)
    token = await make_access_token(user)

    resp = await api_client.get(
        "/api/user-groups",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    data = body["data"]
    result = next(item for item in data if item["id"] == group.pk)
    assert result["name"] == group.name
    assert result["user_count"] == 1
    assert result["users_url"].endswith(f"/api/user-groups/{group.pk}/users")

    users_response = await api_client.get(
        result["users_url"],
        headers={"Authorization": f"Bearer {token}"},
    )
    assert users_response.status_code == 200
    assert users_response.json()["data"] == [{"id": user.pk, "name": user.username}]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("role", ["", "user", "coord"])
async def test_list_groups_requires_lab_admin(api_client, user, group, role):
    if role:
        await sync_to_async(_grant_role)(user, role, 97002)
    token = await make_access_token(user)

    for path in ("/api/user-groups", f"/api/user-groups/{group.pk}/users"):
        resp = await api_client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403, path


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_list_groups_no_n_plus_one(api_client, user):
    """Group + prefetched users must resolve in a fixed number of queries."""
    from core.users.tests.factories import GroupFactory, UserFactory

    def _setup():
        groups = [GroupFactory(name=f"group-{i}") for i in range(5)]
        for g in groups:
            u = UserFactory()
            u.groups.add(g)

    await sync_to_async(_setup)()
    await sync_to_async(_grant_role)(user, "admin", 97003)
    token = await make_access_token(user)

    resp = await api_client.get(
        "/api/user-groups",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_list_groups_unauthenticated_returns_401(api_client):
    resp = await api_client.get("/api/user-groups")
    assert resp.status_code == 401
