"""Pytest fixtures for Support Desk domain and API tests."""

import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from core.support_desk.contracts import SystemState
from core.support_desk.models.category import SupportCategory
from core.support_desk.models.priority import SupportPriority
from core.support_desk.models.settings import SupportSettings
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.transition import SupportStatusTransition
from core.users.tests.factories import UserFactory


@pytest.fixture
def requester_user(db):
    return UserFactory(username="requester1", email="requester1@example.com")


@pytest.fixture
def agent_user(db):
    user = UserFactory(username="agent1", email="agent1@example.com")
    group, _ = Group.objects.get_or_create(name="Support Agent")
    user.groups.add(group)
    return user


@pytest.fixture
def admin_user(db):
    user = UserFactory(username="admin1", email="admin1@example.com", is_staff=True)
    group, _ = Group.objects.get_or_create(name="Support Administrator")
    user.groups.add(group)
    return user


@pytest.fixture
def requester_client(requester_user):
    client = APIClient()
    client.force_authenticate(user=requester_user)
    return client


@pytest.fixture
def agent_client(agent_user):
    client = APIClient()
    client.force_authenticate(user=agent_user)
    return client


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def support_setup(db):
    """Seed base support configuration entities."""
    category = SupportCategory.objects.create(
        name="General Hardware",
        description="Issues related to physical lab instruments",
        sort_order=1,
        is_active=True,
    )
    priority_low = SupportPriority.objects.create(name="Low", rank=1, is_default=False, is_active=True)
    priority_med = SupportPriority.objects.create(name="Medium", rank=2, is_default=True, is_active=True)
    priority_high = SupportPriority.objects.create(name="High", rank=3, is_default=False, is_active=True)

    status_open = SupportStatus.objects.create(
        name="Open",
        system_state=SystemState.OPEN.value,
        is_initial=True,
        is_active=True,
        sort_order=1,
    )
    status_active = SupportStatus.objects.create(
        name="In Progress",
        system_state=SystemState.ACTIVE.value,
        is_initial=False,
        is_active=True,
        sort_order=2,
    )
    status_resolved = SupportStatus.objects.create(
        name="Resolved",
        system_state=SystemState.DONE.value,
        is_initial=False,
        is_active=True,
        sort_order=3,
    )
    status_closed = SupportStatus.objects.create(
        name="Closed",
        system_state=SystemState.DONE.value,
        is_initial=False,
        is_final=True,
        is_active=True,
        sort_order=4,
    )

    # Transitions
    t_open_active = SupportStatusTransition.objects.create(
        from_status=status_open,
        to_status=status_active,
        allowed_roles=["agent", "admin"],
        requires_reason=False,
        requires_resolution=False,
    )
    t_active_resolved = SupportStatusTransition.objects.create(
        from_status=status_active,
        to_status=status_resolved,
        allowed_roles=["agent", "admin"],
        requires_reason=False,
        requires_resolution=True,
    )
    t_resolved_open = SupportStatusTransition.objects.create(
        from_status=status_resolved,
        to_status=status_open,
        allowed_roles=["requester", "agent", "admin"],
        requires_reason=True,
        requires_resolution=False,
    )
    t_resolved_closed = SupportStatusTransition.objects.create(
        from_status=status_resolved,
        to_status=status_closed,
        allowed_roles=["agent", "admin"],
        requires_reason=False,
        requires_resolution=False,
    )

    settings = SupportSettings.get_solo()
    settings.reopen_window_days = 14
    settings.auto_close_days = 7
    settings.max_attachment_size_bytes = 10 * 1024 * 1024
    settings.allowed_attachment_extensions = [".png", ".jpg", ".pdf", ".txt"]
    settings.max_attachments_per_ticket = 5
    settings.comment_edit_window_minutes = 15
    settings.save()

    return {
        "category": category,
        "priority_low": priority_low,
        "priority_med": priority_med,
        "priority_high": priority_high,
        "status_open": status_open,
        "status_active": status_active,
        "status_resolved": status_resolved,
        "status_closed": status_closed,
        "t_open_active": t_open_active,
        "t_active_resolved": t_active_resolved,
        "t_resolved_open": t_resolved_open,
        "t_resolved_closed": t_resolved_closed,
        "settings": settings,
    }
