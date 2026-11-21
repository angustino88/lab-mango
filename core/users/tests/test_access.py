"""Labs role resolution from URS group mappings, permission resolution, and the Labs access policy."""

import itertools

import pytest
from django.contrib.auth.models import AnonymousUser, Group
from django.db import IntegrityError, transaction
from rest_framework.test import APIRequestFactory

from core.common.domain.errors import Forbidden
from core.users.access import (
    LabsAccessPolicy,
    clear_labs_roles_cache,
    effective_labs_roles,
    effective_permissions,
    has_permission,
    is_lab_operator,
    require_permission,
    users_with_permission,
)
from core.users.models import URSGroup
from core.users.permissions import ALL_PERMISSIONS, LabsPermission
from core.users.roles import LabsRole
from core.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

_URS_IDS = itertools.count(91000)
_factory = APIRequestFactory()
_ALL = {LabsRole.ADMIN, LabsRole.COORDINATOR, LabsRole.MEMBER}


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

    def test_unknown_role_is_rejected_by_the_database(self):
        group = Group.objects.create(name="access-unknown")
        with pytest.raises(IntegrityError), transaction.atomic():
            URSGroup.objects.create(group=group, urs_group_id=next(_URS_IDS), labs_role="root")

    @pytest.mark.parametrize(
        ("stored_role", "expected"),
        [
            ("admin", {LabsRole.ADMIN}),
            ("coord", {LabsRole.COORDINATOR}),
            ("member", {LabsRole.MEMBER}),
        ],
    )
    def test_returns_assigned_roles(self, stored_role, expected):
        assert effective_labs_roles(_user_with_roles(f"access-{stored_role}", stored_role)) == expected

    def test_multiple_groups_combine(self):
        user = _user_with_roles("access-multi", "member", "coord")
        assert effective_labs_roles(user) == {LabsRole.COORDINATOR, LabsRole.MEMBER}

    def test_superuser_holds_admin_role_without_a_query(self, django_assert_num_queries):
        user = _user_with_roles("access-super", superuser=True)
        with django_assert_num_queries(0):
            assert effective_labs_roles(user) == {LabsRole.ADMIN}

    def test_roles_are_cached_per_user_instance(self, django_assert_num_queries):
        user = _user_with_roles("access-cache", "coord")
        with django_assert_num_queries(1):
            effective_labs_roles(user)
            effective_labs_roles(user)
            has_permission(user, LabsPermission.DIRECTORY_READ)
            effective_permissions(user)

    def test_clearing_the_cache_reflects_group_changes(self):
        user = _user_with_roles("access-clear", "member")
        assert effective_labs_roles(user) == {LabsRole.MEMBER}

        group = Group.objects.create(name="access-clear-admin")
        URSGroup.objects.create(group=group, urs_group_id=next(_URS_IDS), labs_role="admin")
        user.groups.add(group)

        assert effective_labs_roles(user) == {LabsRole.MEMBER}
        clear_labs_roles_cache(user)
        assert LabsRole.ADMIN in effective_labs_roles(user)

    def test_clearing_an_uncached_user_is_a_noop(self):
        clear_labs_roles_cache(_user_with_roles("access-noop", "member"))


class TestHasPermission:
    @pytest.mark.parametrize(
        ("stored_role", "permission", "expected"),
        [
            ("admin", LabsPermission.LAB_OPERATIONS_MANAGE, True),
            ("admin", LabsPermission.DIRECTORY_READ, True),
            ("coord", LabsPermission.LAB_OPERATIONS_MANAGE, True),
            ("coord", LabsPermission.DASHBOARD_READ, True),
            ("coord", LabsPermission.DIRECTORY_READ, False),
            ("member", LabsPermission.BENCH_BOOKING_MANAGE_OWN, True),
            ("member", LabsPermission.LAB_OPERATIONS_MANAGE, False),
            ("", LabsPermission.DASHBOARD_READ, False),
        ],
    )
    def test_roles_grant_their_permissions_and_the_implied_ones(self, stored_role, permission, expected):
        user = _user_with_roles(f"access-has-{stored_role or 'blank'}-{permission.value}", stored_role)
        assert has_permission(user, permission) is expected

    def test_superuser_holds_every_permission(self):
        assert effective_permissions(_user_with_roles("access-has-super", superuser=True)) == ALL_PERMISSIONS

    def test_anonymous_and_missing_users_hold_none(self):
        assert effective_permissions(AnonymousUser()) == frozenset()
        assert effective_permissions(None) == frozenset()

    def test_lab_operators_are_coordinators_and_administrators(self):
        assert is_lab_operator(_user_with_roles("access-op-coord", "coord"))
        assert is_lab_operator(_user_with_roles("access-op-admin", "admin"))
        assert not is_lab_operator(_user_with_roles("access-op-member", "member"))

    def test_require_permission_raises_forbidden(self):
        member = _user_with_roles("access-require", "member")
        require_permission(member, LabsPermission.DASHBOARD_READ)
        with pytest.raises(Forbidden) as caught:
            require_permission(member, LabsPermission.BENCH_BOOKING_APPROVE)
        assert caught.value.code == "permission_denied"


class TestLabsAccessPolicy:
    POLICY = LabsAccessPolicy.of(
        "TestPolicy", read=LabsPermission.DASHBOARD_READ, write=LabsPermission.LAB_OPERATIONS_MANAGE
    )
    READ_ONLY = LabsAccessPolicy.of("TestReadOnly", read=LabsPermission.LEADERBOARD_READ, write=None)

    @pytest.mark.parametrize(
        ("role", "reads", "writes"),
        [("admin", True, True), ("coord", True, True), ("member", True, False), ("", False, False)],
    )
    def test_reads_and_writes_follow_their_permission(self, role, reads, writes):
        user = _user_with_roles(f"access-policy-{role or 'blank'}", role)
        for method in ("GET", "HEAD", "OPTIONS"):
            assert self.POLICY().has_permission(_request(method, user), view=None) is reads, method
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert self.POLICY().has_permission(_request(method, user), view=None) is writes, method

    def test_a_read_only_policy_denies_writes_to_everyone(self):
        user = _user_with_roles("access-policy-readonly", superuser=True)
        assert self.READ_ONLY().has_permission(_request("GET", user), view=None)
        assert not self.READ_ONLY().has_permission(_request("POST", user), view=None)

    @pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
    def test_anonymous_is_denied(self, method):
        assert not self.POLICY().has_permission(_request(method, AnonymousUser()), view=None)

    def test_policy_documents_its_permissions(self):
        assert self.POLICY.__name__ == "TestPolicy"
        assert self.POLICY.__doc__ == "Reads: dashboard.read. Writes: lab_operations.manage."


class TestUsersWithPermission:
    def test_includes_implied_roles_and_superusers_only_once(self, django_assert_num_queries):
        admin = _user_with_roles("holder-admin", "admin", "coord")
        coord = _user_with_roles("holder-coord", "coord")
        _user_with_roles("holder-member", "member")
        _user_with_roles("holder-none")
        superuser = _user_with_roles("holder-super", superuser=True)
        inactive = _user_with_roles("holder-inactive", "admin")
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])

        with django_assert_num_queries(1):
            holders = list(users_with_permission(LabsPermission.LAB_OPERATIONS_MANAGE))

        assert sorted(u.pk for u in holders) == sorted([admin.pk, coord.pk, superuser.pk])
