"""Labs role resolution from URS group mappings, and the Labs permission classes."""

import itertools

import pytest
from django.contrib.auth.models import AnonymousUser, Group
from rest_framework.test import APIRequestFactory

from core.users.access import (
    IsLabAdmin,
    IsLabCoordinator,
    IsLabMember,
    LabsRole,
    clear_labs_roles_cache,
    effective_labs_roles,
    has_labs_role,
)
from core.users.models import URSGroup
from core.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

_URS_IDS = itertools.count(91000)
_factory = APIRequestFactory()
_ALL = {LabsRole.ADMIN, LabsRole.COORDINATOR, LabsRole.USER}


def _user_with_roles(username: str, *roles: str, superuser: bool = False):
    user = UserFactory(username=username, is_superuser=superuser)
    for role in roles:
        group, _ = Group.objects.get_or_create(name=f"access-{role or 'blank'}-{username}")
        URSGroup.objects.create(group=group, urs_group_id=next(_URS_IDS), labs_role=role)
        user.groups.add(group)
    return user


def _request(method: str, user):
    request = getattr(_factory, method.lower())("/")
    request.user = user
    return request


class TestEffectiveLabsRoles:
    def test_anonymous_and_missing_users_hold_no_roles(self):
        assert effective_labs_roles(AnonymousUser()) == frozenset()
        assert effective_labs_roles(None) == frozenset()

    def test_user_without_groups_holds_no_roles(self):
        assert effective_labs_roles(_user_with_roles("access-none")) == frozenset()

    def test_group_without_labs_role_grants_nothing(self):
        assert effective_labs_roles(_user_with_roles("access-blank", "")) == frozenset()

    def test_unknown_stored_role_is_ignored(self):
        assert effective_labs_roles(_user_with_roles("access-unknown", "root")) == frozenset()

    @pytest.mark.parametrize(
        ("stored_role", "expected"),
        [
            ("admin", _ALL),
            ("coord", {LabsRole.COORDINATOR, LabsRole.USER}),
            ("user", {LabsRole.USER}),
        ],
    )
    def test_higher_roles_imply_lower_roles(self, stored_role, expected):
        assert effective_labs_roles(_user_with_roles(f"access-{stored_role}", stored_role)) == expected

    def test_multiple_groups_combine(self):
        user = _user_with_roles("access-multi", "user", "coord")
        assert effective_labs_roles(user) == {LabsRole.COORDINATOR, LabsRole.USER}

    def test_superuser_holds_every_role_without_a_query(self, django_assert_num_queries):
        user = _user_with_roles("access-super", superuser=True)
        with django_assert_num_queries(0):
            assert effective_labs_roles(user) == _ALL

    def test_roles_are_cached_per_user_instance(self, django_assert_num_queries):
        user = _user_with_roles("access-cache", "coord")
        with django_assert_num_queries(1):
            effective_labs_roles(user)
            effective_labs_roles(user)
            has_labs_role(user, LabsRole.ADMIN)

    def test_clearing_the_cache_reflects_group_changes(self):
        user = _user_with_roles("access-clear", "user")
        assert effective_labs_roles(user) == {LabsRole.USER}

        group = Group.objects.create(name="access-clear-admin")
        URSGroup.objects.create(group=group, urs_group_id=next(_URS_IDS), labs_role="admin")
        user.groups.add(group)

        assert effective_labs_roles(user) == {LabsRole.USER}
        clear_labs_roles_cache(user)
        assert LabsRole.ADMIN in effective_labs_roles(user)

    def test_clearing_an_uncached_user_is_a_noop(self):
        clear_labs_roles_cache(_user_with_roles("access-noop", "user"))


class TestHasLabsRole:
    @pytest.mark.parametrize(
        ("stored_role", "role", "expected"),
        [
            ("admin", LabsRole.COORDINATOR, True),
            ("coord", LabsRole.COORDINATOR, True),
            ("coord", LabsRole.ADMIN, False),
            ("user", LabsRole.COORDINATOR, False),
            ("", LabsRole.USER, False),
        ],
    )
    def test_role_checks(self, stored_role, role, expected):
        user = _user_with_roles(f"access-has-{stored_role or 'blank'}-{role}", stored_role)
        assert has_labs_role(user, role) is expected

    def test_superuser_holds_every_role(self):
        assert has_labs_role(_user_with_roles("access-has-super", superuser=True), LabsRole.ADMIN)

    def test_anonymous_holds_none(self):
        assert not has_labs_role(AnonymousUser(), LabsRole.USER)


class TestLabsPermissionClasses:
    @pytest.mark.parametrize(
        ("permission", "allowed_roles"),
        [
            (IsLabAdmin, {"admin"}),
            (IsLabCoordinator, {"admin", "coord"}),
            (IsLabMember, {"admin", "coord", "user"}),
        ],
    )
    @pytest.mark.parametrize("role", ["admin", "coord", "user", ""])
    def test_write_matrix(self, permission, allowed_roles, role):
        user = _user_with_roles(f"access-w-{role or 'blank'}", role)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            allowed = permission().has_permission(_request(method, user), view=None)
            assert allowed is (role in allowed_roles), method

    @pytest.mark.parametrize("permission", [IsLabAdmin, IsLabCoordinator, IsLabMember])
    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    def test_reads_allow_any_authenticated_user(self, permission, method):
        assert permission().has_permission(_request(method, _user_with_roles("access-reader")), view=None)

    @pytest.mark.parametrize("permission", [IsLabAdmin, IsLabCoordinator, IsLabMember])
    @pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
    def test_anonymous_is_denied(self, permission, method):
        assert not permission().has_permission(_request(method, AnonymousUser()), view=None)

    @pytest.mark.parametrize("permission", [IsLabAdmin, IsLabCoordinator, IsLabMember])
    def test_superuser_can_write(self, permission):
        user = _user_with_roles("access-w-super", superuser=True)
        assert permission().has_permission(_request("POST", user), view=None)
