"""URS sync safety: malformed answers, the removal brake, account matching and outcome recording."""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.db import IntegrityError, transaction

from core.users.features.urs_sync.sync_group.service import sync_urs_group
from core.users.models import URSGroup, User
from core.users.tests.factories import GroupFactory, URSGroupFactory, UserFactory

pytestmark = pytest.mark.django_db

_POST = "core.users.features.urs_sync.sync_group.service.requests.post"


@pytest.fixture(autouse=True)
def _urs_settings(settings):
    settings.URS_API_URL = "https://urs.example.test/service/info"
    settings.URS_SYNC_SAFETY_BRAKE = True
    settings.URS_SYNC_BRAKE_MIN_MEMBERS = 4
    settings.URS_SYNC_MAX_REMOVAL_RATIO = 0.5


def _answer(*members, status=200, text=None):
    body = text if text is not None else json.dumps({"Info": {"UserMembers": list(members)}})
    return MagicMock(status_code=status, text=body)


def _group_with_members(name, *usernames):
    group = GroupFactory(name=name)
    urs_group = URSGroupFactory(group=group)
    users = [UserFactory(username=u, is_urs_managed=True, is_active=True) for u in usernames]
    group.user_set.add(*users)
    return urs_group, group, users


def _sync(urs_group, response, **kwargs):
    with patch(_POST, return_value=response):
        return sync_urs_group(URSGroup.objects.filter(pk=urs_group.pk), **kwargs)


def test_empty_answer_is_blocked_and_keeps_members():
    urs_group, group, users = _group_with_members("brake-empty", "keep_a")

    report = _sync(urs_group, _answer())

    urs_group.refresh_from_db()
    users[0].refresh_from_db()
    assert report.blocked == [str(urs_group)]
    assert group.user_set.filter(pk=users[0].pk).exists()
    assert users[0].is_active is True
    assert urs_group.last_sync_status == URSGroup.SyncStatus.BLOCKED
    assert "no members" in urs_group.last_sync_message


def test_large_removal_is_blocked_until_forced():
    urs_group, group, _ = _group_with_members("brake-ratio", "m_a", "m_b", "m_c", "m_d")

    blocked = _sync(urs_group, _answer("apac\\m_a"))
    assert blocked.blocked and group.user_set.count() == 4

    forced = _sync(urs_group, _answer("apac\\m_a"), force=True)
    urs_group.refresh_from_db()
    assert forced.applied and group.user_set.count() == 1
    assert urs_group.last_sync_status == URSGroup.SyncStatus.APPLIED
    assert "(forced)" in urs_group.last_sync_message


def test_removal_within_limit_applies():
    urs_group, group, _ = _group_with_members("brake-ok", "w_a", "w_b", "w_c", "w_d")

    report = _sync(urs_group, _answer("apac\\w_a", "apac\\w_b", "apac\\w_c"))

    assert report.applied and report.memberships_removed == 1
    assert group.user_set.count() == 3


@pytest.mark.parametrize(
    "response",
    [
        _answer(status=500),
        _answer(text="not json"),
        _answer(text=json.dumps({"Info": {}})),
        _answer(text=json.dumps({"Info": {"UserMembers": "apac\\x"}})),
        _answer(text=json.dumps([])),
    ],
)
def test_malformed_answer_fails_and_keeps_members(response):
    urs_group, group, users = _group_with_members("malformed", "kept_member")

    report = _sync(urs_group, response)

    urs_group.refresh_from_db()
    assert report.failed == [str(urs_group)]
    assert group.user_set.filter(pk=users[0].pk).exists()
    assert urs_group.last_sync_status == URSGroup.SyncStatus.FAILED


def test_request_error_fails_the_group_only():
    import requests

    urs_group = URSGroupFactory(group=GroupFactory(name="network-error"))
    with patch(_POST, side_effect=requests.ConnectionError("down")):
        report = sync_urs_group(URSGroup.objects.filter(pk=urs_group.pk))

    urs_group.refresh_from_db()
    assert report.failed == [str(urs_group)]
    assert urs_group.last_sync_message == "URS request failed (ConnectionError)."


def test_group_without_django_group_gets_one_and_syncs():
    urs_group = URSGroupFactory(group=None, urs_group_name="Unlinked team")

    report = _sync(urs_group, _answer("apac\\linked_member"))

    urs_group.refresh_from_db()
    assert report.applied == [str(urs_group)]
    assert urs_group.group.name == "Unlinked team"
    assert urs_group.group.user_set.filter(username="linked_member").exists()


def test_existing_account_is_matched_case_insensitively_without_duplicates():
    urs_group = URSGroupFactory(group=GroupFactory(name="case-match"))
    existing = UserFactory(username="ABC1HC", is_urs_managed=True)

    _sync(urs_group, _answer("APAC\\abc1hc"))

    assert User.objects.filter(username__iexact="abc1hc").count() == 1
    assert urs_group.group.user_set.filter(pk=existing.pk).exists()


def test_locally_managed_account_is_never_added():
    urs_group = URSGroupFactory(group=GroupFactory(name="unmanaged"))
    local = UserFactory(username="local_admin", is_urs_managed=False)

    report = _sync(urs_group, _answer("apac\\local_admin", "apac\\new_member"))

    assert report.skipped_unmanaged == 1
    assert not urs_group.group.user_set.filter(pk=local.pk).exists()
    assert urs_group.group.user_set.filter(username="new_member").exists()


def test_unusable_member_names_are_skipped_and_reported():
    urs_group = URSGroupFactory(group=GroupFactory(name="bad-names"))
    too_long = "apac\\" + "x" * 151

    report = _sync(urs_group, _answer("no-domain", "apac\\", too_long, "apac\\bad name", 7, "apac\\good_one"))

    urs_group.refresh_from_db()
    assert report.applied and report.invalid_members == 5
    assert list(urs_group.group.user_set.values_list("username", flat=True)) == ["good_one"]
    assert "5 unusable member name(s)" in urs_group.last_sync_message


def test_new_member_becomes_inactive_free_stub():
    urs_group = URSGroupFactory(group=GroupFactory(name="stub"))

    report = _sync(urs_group, _answer("apac\\brand_new"))

    stub = User.objects.get(username="brand_new")
    assert report.users_created == 1
    assert stub.is_urs_managed is True and stub.is_active is True
    assert stub.has_usable_password() is False


def test_running_twice_converges():
    urs_group, group, _ = _group_with_members("twice", "t_a", "t_b")
    answer = _answer("apac\\t_a", "apac\\t_c")

    _sync(urs_group, answer)
    second = _sync(urs_group, answer)

    assert set(group.user_set.values_list("username", flat=True)) == {"t_a", "t_c"}
    assert second.memberships_added == 0 and second.memberships_removed == 0 and second.users_created == 0


def test_blocked_group_does_not_stop_other_groups():
    blocked_group, blocked_django_group, _ = _group_with_members("multi-blocked", "b_a")
    ok_group = URSGroupFactory(group=GroupFactory(name="multi-ok"))
    answers = {blocked_group.urs_group_id: _answer(), ok_group.urs_group_id: _answer("apac\\ok_member")}

    def fake_post(*, url, data, **kwargs):
        return answers[json.loads(data)["serviceId"]]

    with patch(_POST, side_effect=fake_post):
        report = sync_urs_group(URSGroup.objects.filter(pk__in=[blocked_group.pk, ok_group.pk]))

    assert report.blocked == [str(blocked_group)] and report.applied == [str(ok_group)]
    assert blocked_django_group.user_set.count() == 1
    assert ok_group.group.user_set.filter(username="ok_member").exists()


def test_database_rejects_case_variant_usernames_and_duplicate_urs_ids():
    UserFactory(username="dup_case")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create(username="DUP_CASE")
    existing = URSGroupFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        URSGroup.objects.create(urs_group_id=existing.urs_group_id)


def test_without_the_safety_brake_everything_applies_at_once(settings):
    settings.URS_SYNC_SAFETY_BRAKE = False
    urs_group, group, users = _group_with_members("no-brake", "nb_a", "nb_b", "nb_c", "nb_d", "nb_e")

    report = _sync(urs_group, _answer())

    assert report.applied == [str(urs_group)] and report.blocked == []
    assert group.user_set.count() == 0
    for user in users:
        user.refresh_from_db()
        assert user.is_active is False


def test_without_the_safety_brake_a_failed_answer_still_changes_nothing(settings):
    settings.URS_SYNC_SAFETY_BRAKE = False
    urs_group, group, _ = _group_with_members("no-brake-error", "ne_a")

    report = _sync(urs_group, _answer(status=503))

    assert report.failed == [str(urs_group)]
    assert group.user_set.count() == 1
