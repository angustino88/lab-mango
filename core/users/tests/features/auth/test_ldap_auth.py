"""
Unit tests for core.users.features.auth.login.ldap_service.

LDAP connections are mocked — no real LDAP server required.
"""

from unittest.mock import MagicMock, patch

import pytest

from core.users.features.auth.login.ldap_service import ldap_auth
from core.users.tests.factories import UserFactory


@pytest.mark.django_db
class TestLdapAuthWhitelist:
    def test_whitelist_user_calls_django_authenticate(self, settings):
        """admin/adminlab go through Django's ModelBackend, not LDAP."""
        user = UserFactory(username="adminlab")
        user.set_password("secret")
        user.save()

        result = ldap_auth("adminlab", "secret")
        assert result is not None
        assert result.username == "adminlab"

    def test_whitelist_wrong_password_returns_none(self):
        UserFactory(username="adminlab")
        result = ldap_auth("adminlab", "wrongpassword")
        assert result is None

    def test_whitelist_check_is_case_insensitive(self):
        """'ADMINLAB' should still hit the whitelist path."""
        with patch("core.users.features.auth.login.ldap_service.authenticate", return_value=None) as mock_auth:
            ldap_auth("ADMINLAB", "x")
            mock_auth.assert_called_once_with(username="ADMINLAB", password="x")


@pytest.mark.django_db
class TestLdapAuthLDAPPath:
    def _make_ldap_entry(self, username: str) -> MagicMock:
        entry = MagicMock()
        entry.entry_attributes_as_dict = {
            "givenName": ["Test"],
            "sn": ["User"],
            "mail": [f"{username}@bosch.com"],
            "name": [username],
            "displayName": [f"Test User ({username})"],
            "department": ["EDA-XC"],
        }
        return entry

    def test_successful_ldap_auth_updates_provisioned_user(self):
        username = "bge2hc"
        UserFactory(username=username)
        entry = self._make_ldap_entry(username)

        with patch("core.users.features.auth.login.ldap_service.Connection") as MockConn, \
             patch("core.users.features.auth.login.ldap_service.Server"):
            MockConn.return_value.entries = [entry]
            user = ldap_auth(username, "secret")
            MockConn.return_value.unbind.assert_called_once()
            assert "sAMAccountName=" in MockConn.return_value.search.call_args.kwargs["search_filter"]

        assert user is not None
        assert user.username == username
        assert user.email == f"{username}@bosch.com"
        assert user.first_name == "Test"
        assert user.display_name == f"Test User ({username})"
        assert user.department == "EDA-XC"

    def test_successful_ldap_auth_updates_existing_user(self):
        username = "bge2hc"
        existing = UserFactory(username=username, first_name="Old", department="OLD")
        entry = self._make_ldap_entry(username)

        with patch("core.users.features.auth.login.ldap_service.Connection") as MockConn, \
             patch("core.users.features.auth.login.ldap_service.Server"):
            MockConn.return_value.entries = [entry]
            user = ldap_auth(username, "secret")

        assert user.pk == existing.pk
        existing.refresh_from_db()
        assert existing.first_name == "Test"
        assert existing.department == "EDA-XC"

    def test_empty_ldap_response_returns_none(self):
        with patch("core.users.features.auth.login.ldap_service.Connection") as MockConn, \
             patch("core.users.features.auth.login.ldap_service.Server"):
            MockConn.return_value.entries = []
            result = ldap_auth("unknown_user", "x")

        assert result is None

    def test_ldap_connection_error_returns_none(self):
        with patch("core.users.features.auth.login.ldap_service.Connection", side_effect=OSError("LDAP down")), \
             patch("core.users.features.auth.login.ldap_service.Server"):
            result = ldap_auth("bge2hc", "secret")

        assert result is None

    def test_unexpected_programming_errors_propagate(self):
        """Unexpected defects must not masquerade as invalid credentials."""
        with patch("core.users.features.auth.login.ldap_service.Connection", side_effect=RuntimeError("boom")), \
             patch("core.users.features.auth.login.ldap_service.Server"):
            with pytest.raises(RuntimeError):
                ldap_auth("bge2hc", "x")
