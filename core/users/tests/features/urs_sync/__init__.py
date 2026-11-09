from unittest.mock import MagicMock, patch

import pytest

from core.users.tests.factories import GroupFactory, URSGroupFactory, UserFactory


@pytest.mark.django_db
def test_sync_urs_group_adds_new_user_to_group(db):
    """Users returned by URS API that exist in DB should be added to the group."""
    from core.users.features.urs_sync.sync_group.service import sync_urs_group
    from core.users.models import URSGroup

    grp = GroupFactory(name="lab-coord")
    urs_group = URSGroupFactory(group=grp)
    user = UserFactory(username="nbo0hc", is_urs_managed=True)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"Info": {"UserMembers": ["apac\\\\nbo0hc"]}}'

    with patch("core.users.features.urs_sync.sync_group.service.requests.post", return_value=mock_response):
        sync_urs_group(URSGroup.objects.filter(pk=urs_group.pk))

    user.refresh_from_db()
    assert grp.user_set.filter(pk=user.pk).exists()


@pytest.mark.django_db
def test_sync_urs_group_removes_user_no_longer_in_urs(db):
    """Users that were in the Django group but removed from URS should be removed."""
    from core.users.features.urs_sync.sync_group.service import sync_urs_group
    from core.users.models import URSGroup

    grp = GroupFactory(name="lab-staff")
    urs_group = URSGroupFactory(group=grp)
    user = UserFactory(username="removed_user", is_urs_managed=True)
    grp.user_set.add(user)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"Info": {"UserMembers": []}}'

    with patch("core.users.features.urs_sync.sync_group.service.requests.post", return_value=mock_response):
        sync_urs_group(URSGroup.objects.filter(pk=urs_group.pk))

    assert not grp.user_set.filter(pk=user.pk).exists()


@pytest.mark.django_db
def test_sync_urs_group_deactivates_users_with_no_groups(db):
    """URS-managed users with no groups after sync must be deactivated."""
    from core.users.features.urs_sync.sync_group.service import sync_urs_group
    from core.users.models import URSGroup

    grp = GroupFactory(name="grp-dactivate")
    urs_group = URSGroupFactory(group=grp)
    user = UserFactory(username="lonely_user", is_urs_managed=True, is_active=True)
    # user is in the group
    grp.user_set.add(user)

    mock_response = MagicMock()
    mock_response.status_code = 200
    # URS returns empty → user removed from group → no groups → deactivated
    mock_response.text = '{"Info": {"UserMembers": []}}'

    with patch("core.users.features.urs_sync.sync_group.service.requests.post", return_value=mock_response):
        sync_urs_group(URSGroup.objects.filter(pk=urs_group.pk))

    user.refresh_from_db()
    assert user.is_active is False


@pytest.mark.django_db
def test_scan_urs_group_task_calls_sync(db):
    """Celery task scan_urs_group should call sync with active URS groups."""
    from core.users.tasks import scan_urs_group

    URSGroupFactory(active=True)
    URSGroupFactory(active=False)

    with patch("core.users.features.urs_sync.sync_group.service.requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"Info": {"UserMembers": []}}'
        mock_post.return_value = mock_response

        scan_urs_group()

    # Only 1 active URS group → 1 API call
    assert mock_post.call_count == 1
