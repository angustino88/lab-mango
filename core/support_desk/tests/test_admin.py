"""Django admin for support categories and priorities."""

import pytest
from django.contrib import admin
from django.urls import reverse

from core.support_desk.models import SupportCategory, SupportPriority
from tests.factories import UserFactory


def test_models_are_registered():
    assert SupportCategory in admin.site._registry
    assert SupportPriority in admin.site._registry


@pytest.mark.django_db
def test_non_admin_staff_cannot_see_config(client):
    user = UserFactory(username="staff1", is_staff=True)
    client.force_login(user)
    assert client.get(reverse("admin:support_desk_supportcategory_changelist")).status_code == 403
    assert client.get(reverse("admin:support_desk_supportpriority_changelist")).status_code == 403


@pytest.mark.django_db
def test_support_admin_creates_and_edits_category(client, admin_user):
    client.force_login(admin_user)
    url = reverse("admin:support_desk_supportcategory_add")
    assert client.get(url).status_code == 200
    resp = client.post(url, {"name": "Hardware", "code": "", "description": "", "is_active": "on", "sort_order": 1})
    assert resp.status_code == 302
    cat = SupportCategory.objects.get(name="Hardware")
    assert cat.code == "hardware"
    resp = client.post(
        reverse("admin:support_desk_supportcategory_change", args=[cat.pk]),
        {"name": "Hardware 2", "code": "hardware", "description": "", "sort_order": 1},
    )
    assert resp.status_code == 302
    cat.refresh_from_db()
    assert (cat.name, cat.is_active) == ("Hardware 2", False)


@pytest.mark.django_db
def test_support_admin_priority_default_and_sla_validation(client, admin_user):
    client.force_login(admin_user)
    url = reverse("admin:support_desk_supportpriority_add")
    base = {"name": "High", "code": "", "rank": 2, "color_hex": "", "is_active": "on"}
    bad = client.post(url, {**base, "response_target_minutes": 60, "resolution_target_minutes": 30})
    assert bad.status_code == 200
    assert not SupportPriority.objects.exists()
    first = client.post(url, {**base, "is_default": "on"})
    assert first.status_code == 302
    second = client.post(url, {**base, "name": "Low", "rank": 3, "is_default": "on"})
    assert second.status_code == 302
    assert list(SupportPriority.objects.filter(is_default=True).values_list("name", flat=True)) == ["Low"]


@pytest.mark.django_db
def test_delete_is_not_allowed(client, admin_user):
    cat = SupportCategory.objects.create(name="X", code="x")
    client.force_login(admin_user)
    assert client.get(reverse("admin:support_desk_supportcategory_delete", args=[cat.pk])).status_code == 403


@pytest.mark.django_db
def test_support_admin_manages_statuses_with_flag_validation(client, admin_user):
    from core.support_desk.models import SupportStatus

    assert SupportStatus in admin.site._registry
    client.force_login(admin_user)
    url = reverse("admin:support_desk_supportstatus_add")
    base = {"name": "Open", "system_state": "open", "color_hex": "", "sort_order": 1, "is_active": "on"}
    bad = client.post(url, {**base, "is_final": "on"})
    assert bad.status_code == 200
    assert not SupportStatus.objects.exists()
    assert client.post(url, {**base, "is_initial": "on"}).status_code == 302
    assert client.post(url, {**base, "name": "Triage", "is_initial": "on"}).status_code == 302
    assert list(SupportStatus.objects.filter(is_initial=True).values_list("name", flat=True)) == ["Triage"]


@pytest.mark.django_db
def test_non_admin_staff_cannot_see_statuses(client):
    client.force_login(UserFactory(is_staff=True))
    assert client.get(reverse("admin:support_desk_supportstatus_changelist")).status_code == 403
