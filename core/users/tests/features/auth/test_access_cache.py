"""Tests for cross-request user Labs role cache and EntraIdentity binding cache."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from redis.exceptions import ConnectionError as RedisConnectionError

from core.users.access import clear_labs_roles_cache, effective_labs_roles
from core.users.features.auth.authentication import EntraJWTAuthentication
from core.users.models import EntraIdentity, URSGroup, User
from core.users.roles import LabsRole
from tests.factories import UserFactory


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db(transaction=True)
@override_settings(API_AUTH_CACHE_ENABLED=True, API_AUTH_CACHE_TTL=120)
def test_effective_labs_roles_cached_across_instances_and_invalidated_on_group_change():
    user: Any = UserFactory(username="cached-role-user", is_superuser=False, is_staff=False)
    auth_group = AuthGroup.objects.create(name="Role Cache Group")
    urs_group = URSGroup.objects.create(group=auth_group, urs_group_id=777001, labs_role=LabsRole.MEMBER.value)
    user.groups.add(auth_group)

    # First lookup populates Redis/LocMem cache
    fresh_user_1 = User.objects.get(pk=user.pk)
    assert effective_labs_roles(fresh_user_1) == frozenset({LabsRole.MEMBER.value})

    # Second lookup on a brand-new User instance hits cache with 0 DB queries
    fresh_user_2 = User.objects.get(pk=user.pk)
    with CaptureQueriesContext(connection) as queries:
        roles = effective_labs_roles(fresh_user_2)
    assert roles == frozenset({LabsRole.MEMBER.value})
    assert len(queries) == 0

    # Changing URSGroup.labs_role bumps namespace on commit -> fresh read reflects new role immediately
    urs_group.labs_role = LabsRole.COORDINATOR.value
    urs_group.save(update_fields=["labs_role"])

    fresh_user_3 = User.objects.get(pk=user.pk)
    assert effective_labs_roles(fresh_user_3) == frozenset({LabsRole.COORDINATOR.value})

    # Removing group membership invalidates immediately via m2m_changed signal
    user.groups.remove(auth_group)
    fresh_user_4 = User.objects.get(pk=user.pk)
    assert effective_labs_roles(fresh_user_4) == frozenset()

    # Explicit clear_labs_roles_cache works cleanly
    clear_labs_roles_cache(fresh_user_4)

    # Outage fallback still reads accurately from DB
    user.groups.add(auth_group)
    fresh_user_5 = User.objects.get(pk=user.pk)
    with patch("core.common.cache.cache.get", side_effect=RedisConnectionError("redis down")):
        assert effective_labs_roles(fresh_user_5) == frozenset({LabsRole.COORDINATOR.value})


@pytest.mark.django_db(transaction=True)
@override_settings(API_AUTH_CACHE_ENABLED=True, API_AUTH_CACHE_TTL=120)
def test_entra_jwt_authentication_caches_binding_and_invalidates_on_unlink():
    user: Any = UserFactory(username="cached-entra-user", is_active=True)
    tid = uuid.uuid4()
    oid = uuid.uuid4()
    binding = EntraIdentity.objects.create(user=user, tenant_id=tid, object_id=oid)

    auth = EntraJWTAuthentication()
    token = {"auth_source": "entra", "user_id": user.pk, "entra_tid": str(tid), "entra_oid": str(oid)}

    # 1. Cold check queries User + EntraIdentity (2 queries)
    with CaptureQueriesContext(connection) as cold_queries:
        resolved = auth.get_user(token)
    assert resolved.pk == user.pk
    assert len(cold_queries) == 2

    # 2. Warm check serves verified user from cache with 0 DB queries
    with CaptureQueriesContext(connection) as warm_queries:
        resolved2 = auth.get_user(token)
    assert resolved2.pk == user.pk
    assert len(warm_queries) == 0

    # 3. Unlinking EntraIdentity immediately invalidates the cache -> token rejected
    binding.delete()
    from rest_framework.exceptions import AuthenticationFailed

    with pytest.raises(AuthenticationFailed):
        auth.get_user(token)

    # 4. Re-bind, warm cache, then deactivate user -> immediately rejected
    EntraIdentity.objects.create(user=user, tenant_id=tid, object_id=oid)
    assert auth.get_user(token).pk == user.pk
    user.is_active = False
    user.save(update_fields=["is_active"])
    with pytest.raises(AuthenticationFailed):
        auth.get_user(token)
