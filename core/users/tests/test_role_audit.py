"""Role audit log (append-only) and the access review screen."""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import Group
from django.db import DatabaseError, transaction
from django.test import Client

from core.users.features.urs_sync.sync_group.service import sync_urs_group
from core.users.models import RoleAuditEvent, URSGroup, User
from core.users.tests.factories import GroupFactory, URSGroupFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def root_client():
    client = Client()
    client.force_login(UserFactory(username="audit_root", is_staff=True, is_superuser=True))
    return client


def _events(event_type):
    return list(RoleAuditEvent.objects.filter(event_type=event_type))


def test_events_cannot_be_changed_or_deleted():
    event = RoleAuditEvent.objects.create(event_type="urs_group_created", actor_label="tester")

    with pytest.raises(DatabaseError), transaction.atomic():
        RoleAuditEvent.objects.filter(pk=event.pk).update(actor_label="someone else")
    with pytest.raises(DatabaseError), transaction.atomic():
        RoleAuditEvent.objects.filter(pk=event.pk).delete()


def test_deleting_a_user_keeps_their_history():
    user = UserFactory(username="leaver")
    RoleAuditEvent.objects.create(
        event_type="user_activity_changed", actor_label="system", target_user_id=user.pk, target_label="leaver"
    )

    user.delete()

    assert RoleAuditEvent.objects.filter(target_label="leaver").exists()


def test_changing_a_urs_group_role_is_recorded(root_client, django_capture_on_commit_callbacks):
    urs_group = URSGroupFactory(urs_group_name="Coordinators", labs_role="user")
    with patch("core.users.admin.sync_selected_urs_groups.delay"), django_capture_on_commit_callbacks(execute=True):
        response = root_client.post(
            f"/admin/users/ursgroup/{urs_group.pk}/change/",
            {
                "urs_group_name": "Coordinators",
                "urs_group_id": urs_group.urs_group_id,
                "labs_role": "coord",
                "active": "on",
            },
        )

    assert response.status_code == 302, response.content
    (event,) = _events("urs_group_changed")
    assert event.actor_label == "audit_root"
    assert event.changes == {"labs_role": {"before": "user", "after": "coord"}}


def test_creating_and_deleting_a_urs_group_is_recorded(root_client, django_capture_on_commit_callbacks):
    with patch("core.users.admin.sync_selected_urs_groups.delay"), django_capture_on_commit_callbacks(execute=True):
        root_client.post(
            "/admin/users/ursgroup/add/",
            {"urs_group_name": "New admins", "urs_group_id": 77001, "labs_role": "admin", "active": "on"},
        )
    urs_group = URSGroup.objects.get(urs_group_id=77001)
    root_client.post(f"/admin/users/ursgroup/{urs_group.pk}/delete/", {"post": "yes"})

    (created,) = _events("urs_group_created")
    (deleted,) = _events("urs_group_deleted")
    assert created.changes["labs_role"] == {"before": None, "after": "admin"}
    assert deleted.changes["labs_role"] == {"before": "admin", "after": None}


def test_granting_superuser_in_admin_is_recorded(root_client):
    target = UserFactory(username="promoted")
    form = {
        "username": "promoted",
        "is_superuser": "on",
        "is_staff": "on",
        "is_urs_managed": "on",
        "date_joined_0": "2026-01-01",
        "date_joined_1": "00:00:00",
        "initial-date_joined_0": "2026-01-01",
        "initial-date_joined_1": "00:00:00",
    }

    response = root_client.post(f"/admin/users/user/{target.pk}/change/", form)

    assert response.status_code == 302, response.content.decode()[:2000]
    (event,) = _events("user_privileges_changed")
    assert event.target_label == "promoted"
    assert event.changes["is_superuser"] == {"before": False, "after": True}
    assert event.changes["is_staff"] == {"before": False, "after": True}


def test_urs_sync_records_membership_and_deactivation(settings):
    settings.URS_API_URL = "https://urs.example.test/service/info"
    group = GroupFactory(name="audit-sync")
    urs_group = URSGroupFactory(group=group, labs_role="coord", urs_group_name="Audit sync")
    leaving = UserFactory(username="leaving_member", is_urs_managed=True)
    group.user_set.add(leaving)
    answer = MagicMock(status_code=200, text=json.dumps({"Info": {"UserMembers": ["apac\\\\joining_member"]}}))

    with patch("core.users.features.urs_sync.sync_group.service.requests.post", return_value=answer):
        sync_urs_group(URSGroup.objects.filter(pk=urs_group.pk))

    (membership,) = _events("urs_sync_membership")
    assert membership.actor_label == "system:urs-sync"
    assert membership.changes == {
        "labs_role": "coord",
        "added": ["joining_member"],
        "removed": ["leaving_member"],
        "forced": False,
    }
    (deactivated,) = _events("user_activity_changed")
    assert deactivated.target_label == "leaving_member"
    assert deactivated.changes == {"is_active": {"before": True, "after": False}}


def test_access_review_lists_privileged_users_with_their_source(root_client):
    coord_group = Group.objects.create(name="review-coord")
    URSGroup.objects.create(
        group=coord_group, urs_group_id=78001, urs_group_name="Lab coordinators", labs_role="coord"
    )
    coordinator = UserFactory(username="review_coordinator")
    coordinator.groups.add(coord_group)
    plain_group = Group.objects.create(name="review-plain")
    URSGroup.objects.create(group=plain_group, urs_group_id=78002, labs_role="user")
    UserFactory(username="review_plain").groups.add(plain_group)

    page = root_client.get("/admin/users/privilegeduser/").content.decode()

    assert "review_coordinator" in page and "Lab coordinators (coord)" in page
    assert "audit_root" in page
    assert "review_plain" not in page

    csv_response = root_client.post(
        "/admin/users/privilegeduser/",
        {"action": "export_csv", "_selected_action": [coordinator.pk]},
    )
    lines = csv_response.content.decode().splitlines()
    assert lines[0].startswith("username,display_name,privileges")
    assert lines[1].startswith("review_coordinator,") and "coord" in lines[1]


def test_audit_and_review_screens_are_superuser_only():
    staff = UserFactory(username="review_staff", is_staff=True)
    client = Client()
    client.force_login(User.objects.get(pk=staff.pk))

    assert client.get("/admin/users/roleauditevent/").status_code == 403
    assert client.get("/admin/users/privilegeduser/").status_code == 403
