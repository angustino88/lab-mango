"""Generic RBAC building blocks: no database and no business roles or capabilities involved."""

from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from rest_framework.test import APIRequestFactory

from core.common.api.permissions import CapabilityPermission, RoleHierarchy, is_authenticated, is_owner

_factory = APIRequestFactory()

HIERARCHY = RoleHierarchy(grants={"owner": ("editor", "viewer"), "editor": ("viewer",), "viewer": ()})


def _user(*capabilities: str, pk: int = 1):
    return SimpleNamespace(is_authenticated=True, pk=pk, capabilities=frozenset(capabilities))


def _request(method: str, user):
    request = getattr(_factory, method.lower())("/")
    request.user = user
    return request


class _TestPermission(CapabilityPermission):
    """Resolves capabilities straight from the fake user."""

    def resolve_capabilities(self, user):
        return user.capabilities


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


class TestCapabilityPermission:
    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_writes_require_the_write_capability(self, method):
        permission = _TestPermission.requiring(read="page.read", write="page.edit", name="Pages")()
        assert permission.has_permission(_request(method, _user("page.edit")), view=None)
        assert not permission.has_permission(_request(method, _user("page.read")), view=None)
        assert not permission.has_permission(_request(method, _user()), view=None)

    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    def test_reads_require_the_read_capability(self, method):
        permission = _TestPermission.requiring(read="page.read", write="page.edit", name="Pages")()
        assert permission.has_permission(_request(method, _user("page.read")), view=None)
        assert not permission.has_permission(_request(method, _user("page.edit")), view=None)

    @pytest.mark.parametrize("method", ["GET", "POST"])
    def test_a_missing_capability_denies_that_method_class(self, method):
        assert not _TestPermission().has_permission(_request(method, _user("page.read", "page.edit")), view=None)

    def test_read_only_policy_denies_every_write(self):
        permission = _TestPermission.requiring(read="page.read", write=None, name="ReadOnly")()
        assert permission.has_permission(_request("GET", _user("page.read")), view=None)
        assert not permission.has_permission(_request("POST", _user("page.read", "page.edit")), view=None)

    @pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
    def test_anonymous_is_always_denied(self, method):
        permission = _TestPermission.requiring(read="page.read", write="page.edit", name="Pages")()
        assert not permission.has_permission(_request(method, AnonymousUser()), view=None)

    def test_request_without_user_is_denied(self):
        permission = _TestPermission.requiring(read="page.read", write=None, name="Pages")()
        assert not permission.has_permission(_factory.get("/"), view=None)

    def test_requiring_names_the_policy(self):
        policy = _TestPermission.requiring(read="page.read", write=None, name="PageReaders")
        assert policy.__name__ == "PageReaders"
        assert (policy.read_capability, policy.write_capability) == ("page.read", None)

    def test_resolve_capabilities_must_be_implemented(self):
        policy = CapabilityPermission.requiring(read=None, write="page.edit", name="Unresolved")

        with pytest.raises(NotImplementedError):
            policy().has_permission(_request("POST", _user()), view=None)
