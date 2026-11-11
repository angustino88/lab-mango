"""Django admin: role-granting fields are superuser-only, and URS sync runs as a queued task."""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.admin.sites import site
from django.contrib.auth.models import Group, Permission
from django.test import Client, RequestFactory

from core.users.admin import URSGroupAdmin, UserAdmin
from core.users.models import URSGroup, User
from core.users.tests.factories import GroupFactory, URSGroupFactory, UserFactory

pytestmark = pytest.mark.django_db

_ROLE_FIELDS = {"is_staff", "is_superuser", "is_urs_managed", "groups", "user_permissions"}


def _staff_with_all_user_and_urs_permissions():
    staff = UserFactory(username="staff_operator", is_staff=True)
    staff.user_permissions.add(*Permission.objects.filter(content_type__app_label__in=["users", "auth"]))
    return User.objects.get(pk=staff.pk)


def _request(user):
    request = RequestFactory().get("/admin/")
    request.user = user
    return request


def test_staff_cannot_edit_role_granting_user_fields():
    staff = _staff_with_all_user_and_urs_permissions()
    target = UserFactory(username="target_user")
    user_admin = UserAdmin(User, site)

    readonly = set(user_admin.get_readonly_fields(_request(staff), target))

    assert _ROLE_FIELDS <= readonly


def test_superuser_can_edit_role_granting_user_fields():
    superuser = UserFactory(username="root_admin", is_staff=True, is_superuser=True)
    user_admin = UserAdmin(User, site)

    readonly = set(user_admin.get_readonly_fields(_request(superuser), UserFactory(username="t2")))

    assert not (_ROLE_FIELDS & readonly)
    assert {"is_active", "labs_roles"} <= readonly


def test_only_superusers_change_urs_groups_and_group_permissions():
    staff = _staff_with_all_user_and_urs_permissions()
    superuser = UserFactory(username="root_two", is_staff=True, is_superuser=True)
    urs_admin = URSGroupAdmin(URSGroup, site)
    group_admin = site._registry[Group]

    for model_admin in (urs_admin, group_admin):
        assert not model_admin.has_change_permission(_request(staff))
        assert not model_admin.has_add_permission(_request(staff))
        assert not model_admin.has_delete_permission(_request(staff))
        assert model_admin.has_change_permission(_request(superuser))
    assert urs_admin.has_view_permission(_request(staff))


def test_labs_roles_display_shows_effective_roles():
    group = GroupFactory(name="display-coord")
    URSGroup.objects.create(group=group, urs_group_id=98001, labs_role="coord")
    user = UserFactory(username="display_user")
    user.groups.add(group)

    assert UserAdmin(User, site).labs_roles(user) == "coord, user"
    assert UserAdmin(User, site).labs_roles(UserFactory(username="no_roles")) == "none"


def test_admin_sync_action_queues_and_records_outcome(settings):
    settings.URS_API_URL = "https://urs.example.test/service/info"
    superuser = UserFactory(username="sync_root", is_staff=True, is_superuser=True, password="pw-sync-root")
    urs_group = URSGroupFactory(group=GroupFactory(name="admin-sync"))
    client = Client()
    client.force_login(superuser)
    answer = MagicMock(status_code=200, text=json.dumps({"Info": {"UserMembers": ["apac\\queued_member"]}}))

    with patch("core.users.features.urs_sync.sync_group.service.requests.post", return_value=answer):
        response = client.post(
            "/admin/users/ursgroup/",
            {"action": "queue_sync", "_selected_action": [urs_group.pk]},
            follow=True,
        )

    urs_group.refresh_from_db()
    assert response.status_code == 200
    assert urs_group.last_sync_status == URSGroup.SyncStatus.APPLIED
    assert urs_group.group.user_set.filter(username="queued_member").exists()


def test_admin_sync_action_reports_queue_failure_without_details():
    superuser = UserFactory(username="sync_root_2", is_staff=True, is_superuser=True)
    urs_group = URSGroupFactory()
    client = Client()
    client.force_login(superuser)

    with patch("core.users.admin.sync_selected_urs_groups.delay", side_effect=RuntimeError("broker secret")):
        response = client.post(
            "/admin/users/ursgroup/",
            {"action": "queue_sync", "_selected_action": [urs_group.pk]},
            follow=True,
        )

    text = response.content.decode()
    assert "could not be queued" in text
    assert "broker secret" not in text


def test_change_pages_render_for_superuser_and_read_only_for_staff():
    superuser = UserFactory(username="pages_root", is_staff=True, is_superuser=True)
    staff = _staff_with_all_user_and_urs_permissions()
    urs_group = URSGroupFactory()
    target = UserFactory(username="pages_target")
    paths = (
        f"/admin/users/ursgroup/{urs_group.pk}/change/",
        f"/admin/users/user/{target.pk}/change/",
        "/admin/users/ursgroup/",
    )

    for user in (superuser, staff):
        client = Client()
        client.force_login(user)
        for path in paths:
            assert client.get(path).status_code == 200, (user.username, path)

    client = Client()
    client.force_login(staff)
    page = client.get(f"/admin/users/ursgroup/{urs_group.pk}/change/").content.decode()
    assert 'name="labs_role"' not in page


def test_saving_a_urs_group_in_admin_creates_its_django_group():
    superuser = UserFactory(username="save_root", is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(superuser)

    response = client.post(
        "/admin/users/ursgroup/add/",
        {"urs_group_name": "Admin Created", "urs_group_id": 66001, "labs_role": "coord", "active": "on"},
    )

    assert response.status_code == 302, response.content
    urs_group = URSGroup.objects.get(urs_group_id=66001)
    assert urs_group.group is not None and urs_group.group.name == "Admin Created"


def test_django_group_screen_is_hidden_from_staff():
    staff = _staff_with_all_user_and_urs_permissions()
    group_admin = site._registry[Group]

    assert not group_admin.has_module_permission(_request(staff))
    assert not group_admin.has_view_permission(_request(staff))
