from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from core.users.public import BindEntraIdentityInput, bind_entra_identity
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

    with (
        patch("core.users.features.urs_sync.sync_group.service.requests.post", return_value=mock_response),
        patch(
            "core.users.features.urs_sync.sync_group.service.settings.URS_API_URL",
            "https://urs.example.test/service/info",
            create=True,
        ),
    ):
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
    stays = UserFactory(username="staying_user", is_urs_managed=True)
    grp.user_set.add(user, stays)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"Info": {"UserMembers": ["apac\\\\staying_user"]}}'

    with (
        patch("core.users.features.urs_sync.sync_group.service.requests.post", return_value=mock_response),
        patch(
            "core.users.features.urs_sync.sync_group.service.settings.URS_API_URL",
            "https://urs.example.test/service/info",
            create=True,
        ),
    ):
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
    stays = UserFactory(username="other_member", is_urs_managed=True, is_active=True)
    grp.user_set.add(user, stays)

    mock_response = MagicMock()
    mock_response.status_code = 200
    # URS no longer lists the user → removed from group → no groups → deactivated
    mock_response.text = '{"Info": {"UserMembers": ["apac\\\\other_member"]}}'

    with (
        patch("core.users.features.urs_sync.sync_group.service.requests.post", return_value=mock_response),
        patch(
            "core.users.features.urs_sync.sync_group.service.settings.URS_API_URL",
            "https://urs.example.test/service/info",
            create=True,
        ),
    ):
        sync_urs_group(URSGroup.objects.filter(pk=urs_group.pk))

    user.refresh_from_db()
    assert user.is_active is False


@pytest.mark.django_db(transaction=True)
def test_urs_active_flip_publishes_user_routing_tombstone(db, settings):
    from core.labs.models import RoutingEntity
    from core.users.features.urs_sync.sync_group.service import sync_urs_group
    from core.users.models import URSGroup
    from core.users.tests.factories import GroupFactory, URSGroupFactory, UserFactory

    group = GroupFactory(name="routing-deactivation")
    urs_group = URSGroupFactory(group=group)
    user = UserFactory(username="routing_user", is_urs_managed=True, is_active=True)
    tenant_id, object_id = uuid4(), uuid4()
    bind_entra_identity(
        data=BindEntraIdentityInput(user_id=user.pk, tenant_id=tenant_id, object_id=object_id),
    )
    group.user_set.add(user)
    settings.URS_API_URL = "https://urs.example.test/service/info"
    response = MagicMock(status_code=200, text='{"Info": {"UserMembers": []}}')

    with patch("core.users.features.urs_sync.sync_group.service.requests.post", return_value=response):
        # An empty URS answer is blocked by default; the operator forces it.
        sync_urs_group(URSGroup.objects.filter(pk=urs_group.pk), force=True)

    user.refresh_from_db()
    key = f"entra:{tenant_id}:{object_id}"
    assert user.is_active is False
    assert RoutingEntity.objects.get(entity_type="users", key=key).deleted_at is not None


@pytest.mark.django_db(transaction=True)
def test_urs_activation_publishes_user_routing_upsert(db, settings):
    from core.labs.models import RoutingChange, RoutingEntity
    from core.users.features.urs_sync.sync_group.service import sync_urs_group
    from core.users.models import EntraIdentity, URSGroup
    from core.users.tests.factories import GroupFactory, URSGroupFactory, UserFactory

    group = GroupFactory(name="routing-activation")
    urs_group = URSGroupFactory(group=group)
    user = UserFactory(username="routing_activate", is_urs_managed=True, is_active=False)
    tenant_id, object_id = uuid4(), uuid4()
    EntraIdentity.objects.create(user=user, tenant_id=tenant_id, object_id=object_id)
    settings.URS_API_URL = "https://urs.example.test/service/info"
    response = MagicMock(status_code=200, text='{"Info": {"UserMembers": ["apac\\\\routing_activate"]}}')

    with patch("core.users.features.urs_sync.sync_group.service.requests.post", return_value=response):
        sync_urs_group(URSGroup.objects.filter(pk=urs_group.pk))

    user.refresh_from_db()
    key = f"entra:{tenant_id}:{object_id}"
    assert user.is_active is True
    assert RoutingEntity.objects.get(entity_type="users", key=key).deleted_at is None
    assert RoutingChange.objects.filter(entity_type="users", key=key, op=RoutingChange.Operation.UPSERT).exists()


@pytest.mark.django_db
def test_sync_urs_group_preserves_superuser_membership_and_activity(db, settings):
    """A missing URS member must not remove or deactivate a local superuser."""
    from core.users.features.urs_sync.sync_group.service import sync_urs_group
    from core.users.models import URSGroup

    grp = GroupFactory(name="admin-mapped")
    urs_group = URSGroupFactory(group=grp)
    admin = UserFactory(username="local_superuser", is_urs_managed=True, is_superuser=True, is_active=True)
    grp.user_set.add(admin)
    mock_response = MagicMock(status_code=200, text='{"Info": {"UserMembers": []}}')
    settings.URS_API_URL = "https://urs.example.test/service/info"

    with patch("core.users.features.urs_sync.sync_group.service.requests.post", return_value=mock_response):
        sync_urs_group(URSGroup.objects.filter(pk=urs_group.pk))
        sync_urs_group(URSGroup.objects.filter(pk=urs_group.pk))

    admin.refresh_from_db()
    assert grp.user_set.filter(pk=admin.pk).exists()
    assert admin.is_active is True
    assert admin.is_superuser is True


@pytest.mark.django_db
def test_sync_urs_group_preserves_superuser_without_groups(db, settings):
    """The global no-group cleanup must not deactivate a superuser."""
    from core.users.features.urs_sync.sync_group.service import sync_urs_group
    from core.users.models import URSGroup

    admin = UserFactory(username="orphan_superuser", is_urs_managed=True, is_superuser=True, is_active=True)
    urs_group = URSGroupFactory(group=GroupFactory(name="empty-mapped"))
    mock_response = MagicMock(status_code=200, text='{"Info": {"UserMembers": []}}')
    settings.URS_API_URL = "https://urs.example.test/service/info"

    with patch("core.users.features.urs_sync.sync_group.service.requests.post", return_value=mock_response):
        sync_urs_group(URSGroup.objects.filter(pk=urs_group.pk))

    admin.refresh_from_db()
    assert admin.is_active is True


@pytest.mark.django_db
def test_sync_urs_group_skips_when_api_url_is_blank(db, settings):
    from core.users.features.urs_sync.sync_group.service import sync_urs_group
    from core.users.models import URSGroup

    urs_group = URSGroupFactory()
    settings.URS_API_URL = ""

    with (
        patch("core.users.features.urs_sync.sync_group.service.requests.post") as mock_post,
    ):
        sync_urs_group(URSGroup.objects.filter(pk=urs_group.pk))

    mock_post.assert_not_called()


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
