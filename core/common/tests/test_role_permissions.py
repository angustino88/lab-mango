"""Generic role-permission building blocks: no database and no business roles involved."""

from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from rest_framework.test import APIRequestFactory

from core.common.api.permissions import RoleHierarchy, RolePermission, is_authenticated, is_owner

_factory = APIRequestFactory()

HIERARCHY = RoleHierarchy(grants={"owner": ("editor", "viewer"), "editor": ("viewer",), "viewer": ()})


def _user(*roles: str, pk: int = 1):
    return SimpleNamespace(is_authenticated=True, pk=pk, roles=frozenset(roles))


def _request(method: str, user):
    request = getattr(_factory, method.lower())("/")
    request.user = user
    return request


class _TestPermission(RolePermission):
    """Resolves roles straight from the fake user."""

    def resolve_roles(self, user):
        return user.roles


class TestRoleHierarchy:
    def test_roles_lists_every_known_role(self):
        assert HIERARCHY.roles == {"owner", "editor", "viewer"}

    def test_expand_adds_implied_roles(self):
        assert HIERARCHY.expand(["owner"]) == {"owner", "editor", "viewer"}
        assert HIERARCHY.expand(["editor"]) == {"editor", "viewer"}
        assert HIERARCHY.expand(["viewer"]) == {"viewer"}

    def test_expand_combines_assigned_roles(self):
        assert HIERARCHY.expand(["viewer", "editor"]) == {"editor", "viewer"}

    def test_expand_drops_unknown_roles(self):
        assert HIERARCHY.expand(["root", ""]) == frozenset()

    def test_expand_of_nothing_is_empty(self):
        assert HIERARCHY.expand([]) == frozenset()

    def test_empty_hierarchy_knows_no_roles(self):
        assert RoleHierarchy().roles == frozenset()
        assert RoleHierarchy().expand(["anything"]) == frozenset()


class TestIsAuthenticated:
    def test_real_user_is_authenticated(self):
        assert is_authenticated(_user())

    @pytest.mark.parametrize("user", [None, AnonymousUser()])
    def test_missing_and_anonymous_users_are_not(self, user):
        assert not is_authenticated(user)


class TestIsOwner:
    def test_matches_creator_id_by_default(self):
        assert is_owner(_user(pk=7), SimpleNamespace(creator_id=7))

    def test_other_user_is_not_owner(self):
        assert not is_owner(_user(pk=8), SimpleNamespace(creator_id=7))

    def test_custom_owner_field(self):
        assert is_owner(_user(pk=7), SimpleNamespace(owner_id=7), owner_field="owner_id")

    def test_anonymous_is_never_owner(self):
        assert not is_owner(AnonymousUser(), SimpleNamespace(creator_id=None))

    def test_object_without_owner_is_never_owned(self):
        assert not is_owner(_user(pk=7), SimpleNamespace())
        assert not is_owner(_user(pk=7), SimpleNamespace(creator_id=None))


class TestRolePermission:
    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_writes_require_a_write_role(self, method):
        class EditorsWrite(_TestPermission):
            write_roles = ("editor",)

        permission = EditorsWrite()
        assert permission.has_permission(_request(method, _user("editor")), view=None)
        assert not permission.has_permission(_request(method, _user("viewer")), view=None)
        assert not permission.has_permission(_request(method, _user()), view=None)

    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    def test_reads_allow_any_authenticated_user_by_default(self, method):
        assert _TestPermission().has_permission(_request(method, _user()), view=None)

    def test_read_roles_restrict_reads(self):
        class EditorsRead(_TestPermission):
            read_roles = ("editor",)

        permission = EditorsRead()
        assert permission.has_permission(_request("GET", _user("editor")), view=None)
        assert not permission.has_permission(_request("GET", _user("viewer")), view=None)

    def test_empty_write_roles_deny_every_write(self):
        permission = _TestPermission()
        assert not permission.has_permission(_request("POST", _user("owner", "editor")), view=None)

    @pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
    def test_anonymous_is_always_denied(self, method):
        class OpenReads(_TestPermission):
            write_roles = ("editor",)

        assert not OpenReads().has_permission(_request(method, AnonymousUser()), view=None)

    def test_request_without_user_is_denied(self):
        assert not _TestPermission().has_permission(_factory.get("/"), view=None)

    def test_resolve_roles_must_be_implemented(self):
        class WritesNeedRole(RolePermission):
            write_roles = ("editor",)

        with pytest.raises(NotImplementedError):
            WritesNeedRole().has_permission(_request("POST", _user()), view=None)
