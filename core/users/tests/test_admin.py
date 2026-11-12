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
    assert {"is_active", "access_summary", "entra_status"} <= readonly


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


def test_user_list_shows_roles_and_their_urs_groups(django_assert_max_num_queries):
    coord_group = GroupFactory(name="display-coord")
    urs_coord = URSGroup.objects.create(
        group=coord_group, urs_group_id=98001, urs_group_name="Coordinators", labs_role="coord"
    )
    for index in range(5):
        UserFactory(username=f"display_user_{index}").groups.add(coord_group)
    UserFactory(username="display_no_role")
    client = Client()
    client.force_login(UserFactory(username="display_root", is_staff=True, is_superuser=True))

    with django_assert_max_num_queries(12):  # constant: groups and URS groups are prefetched
        page = client.get("/admin/users/user/").content.decode()

    assert "Lab coordinator" in page and "No role" in page and "Superuser" in page
    assert f"/admin/users/ursgroup/{urs_coord.pk}/change/" in page


def test_labs_role_filter_lists_only_that_role():
    group = GroupFactory(name="filter-user-group")
    URSGroup.objects.create(group=group, urs_group_id=98002, labs_role="user")
    UserFactory(username="filter_plain").groups.add(group)
    UserFactory(username="filter_nobody")
    client = Client()
    client.force_login(UserFactory(username="filter_root", is_staff=True, is_superuser=True))

    plain = client.get("/admin/users/user/?labs_role=user").content.decode()
    nobody = client.get("/admin/users/user/?labs_role=none").content.decode()

    assert "filter_plain" in plain and "filter_nobody" not in plain
    assert "filter_nobody" in nobody and "filter_plain" not in nobody


def test_urs_group_page_lists_members_role_rights_and_readable_sync_result():
    group = GroupFactory(name="members-group")
    urs_group = URSGroup.objects.create(
        group=group,
        urs_group_id=98003,
        urs_group_name="Members group",
        labs_role="coord",
        last_sync_status="applied",
        last_sync_message="+3 -1",
    )
    UserFactory(username="member_one", display_name="Member One").groups.add(group)
    client = Client()
    client.force_login(UserFactory(username="members_root", is_staff=True, is_superuser=True))

    page = client.get(f"/admin/users/ursgroup/{urs_group.pk}/change/").content.decode()
    listing = client.get("/admin/users/ursgroup/").content.decode()

    assert "member_one" in page and "Member One" in page
    assert "What this role can do" in page and "URS service ID" in page
    assert "3 added, 1 removed" in page and "3 added, 1 removed" in listing
    assert f"?groups__id__exact={group.pk}" in listing


def test_admin_index_starts_with_people_and_access():
    client = Client()
    client.force_login(UserFactory(username="index_root", is_staff=True, is_superuser=True))

    page = client.get("/admin/").content.decode()

    assert "Lab Mango administration" in page
    assert page.index("People and access") < page.index("Authentication and Authorization") < page.index("Labs")


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


def test_saving_a_urs_group_in_admin_creates_its_django_group_and_syncs_it(django_capture_on_commit_callbacks):
    superuser = UserFactory(username="save_root", is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(superuser)

    with patch("core.users.admin.sync_selected_urs_groups.delay") as queued:
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(
                "/admin/users/ursgroup/add/",
                {"urs_group_name": "Admin Created", "urs_group_id": 66001, "labs_role": "coord", "active": "on"},
            )

    assert response.status_code == 302, response.content
    urs_group = URSGroup.objects.get(urs_group_id=66001)
    assert urs_group.group is not None and urs_group.group.name == "Admin Created"
    queued.assert_called_once_with([urs_group.pk], force=False)


def test_django_group_screen_is_hidden_from_staff():
    staff = _staff_with_all_user_and_urs_permissions()
    group_admin = site._registry[Group]

    assert not group_admin.has_module_permission(_request(staff))
    assert not group_admin.has_view_permission(_request(staff))


def test_forced_sync_action_only_exists_with_the_safety_brake(settings):
    superuser = UserFactory(username="actions_root", is_staff=True, is_superuser=True)
    urs_admin = URSGroupAdmin(URSGroup, site)

    settings.URS_SYNC_SAFETY_BRAKE = False
    assert "queue_forced_sync" not in urs_admin.get_actions(_request(superuser))
    settings.URS_SYNC_SAFETY_BRAKE = True
    assert "queue_forced_sync" in urs_admin.get_actions(_request(superuser))
