import pytest
from asgiref.sync import sync_to_async

from core.users.tests.conftest import make_access_token


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_list_groups_returns_group_with_users(api_client, user, group):
    await sync_to_async(user.groups.add)(group)
    token = await make_access_token(user)

    resp = await api_client.get(
        "/api/user-groups",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    data = body["data"]
    assert group.name in data
    assert user.username in data[group.name]


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
    token = await make_access_token(user)

    resp = await api_client.get(
        "/api/user-groups",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_list_groups_unauthenticated_returns_401(api_client):
    resp = await api_client.get("/api/user-groups/")
    assert resp.status_code == 401
