import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth.models import Group

from core.users.models import URSGroup
from core.users.tests.conftest import make_access_token


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_me_returns_user_with_groups(api_client, user):
    token = await make_access_token(user)

    resp = await api_client.get(
        "/api/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["username"] == user.username
    assert "groups" in body["data"]
    assert body["data"]["effective_roles"] == {"labs": []}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_me_unauthenticated_returns_401(api_client):
    resp = await api_client.get("/api/users/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_me_includes_group_permissions(api_client, user, group):
    from asgiref.sync import sync_to_async
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    def _setup():
        ct, _ = ContentType.objects.get_or_create(app_label="auth", model="user")
        perm, _ = Permission.objects.get_or_create(
            codename="view_user",
            content_type=ct,
            defaults={"name": "Can view user"},
        )
        group.permissions.set([perm])
        user.groups.add(group)
        user.save()

    await sync_to_async(_setup)()

    token = await make_access_token(user)
    resp = await api_client.get(
        "/api/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    group_data = body["data"]["groups"]
    assert len(group_data) == 1
    assert group_data[0]["name"] == group.name
    assert set(group_data[0]) == {"id", "name"}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("assigned_role", "expected_roles"),
    [
        ("admin", ["admin", "coord", "user"]),
        ("coord", ["coord", "user"]),
        ("user", ["user"]),
        ("", []),
    ],
)
async def test_get_me_roles_use_mapping_not_group_name(api_client, user, assigned_role, expected_roles):
    def _setup():
        group = Group.objects.create(name="admin-looking-name")
        user.groups.add(group)
        URSGroup.objects.create(group=group, urs_group_id=987654321, labs_role=assigned_role)
        return group.pk

    group_id = await sync_to_async(_setup)()
    token = await make_access_token(user)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await api_client.get("/api/users/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["effective_roles"] == {"labs": expected_roles}
    assert resp.json()["data"]["groups"] == [{"id": group_id, "name": "admin-looking-name"}]

    await sync_to_async(Group.objects.filter(pk=group_id).update)(name="renamed-in-admin")
    renamed_resp = await api_client.get("/api/users/me", headers=headers)
    assert renamed_resp.status_code == 200
    assert renamed_resp.json()["data"]["effective_roles"] == {"labs": expected_roles}
    assert renamed_resp.json()["data"]["groups"] == [{"id": group_id, "name": "renamed-in-admin"}]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_me_superuser_has_all_effective_roles_without_groups(api_client, user):
    await sync_to_async(type(user).objects.filter(pk=user.pk).update)(is_superuser=True)
    token = await make_access_token(user)
    resp = await api_client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["data"]["effective_roles"] == {"labs": ["admin", "coord", "user"]}
    assert resp.json()["data"]["groups"] == []
