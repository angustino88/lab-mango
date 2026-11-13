"""Django admin for Support Desk categories and priorities: support-admin only, writes via the commands."""

import pytest
from django.contrib import admin
from django.urls import reverse

from core.support_desk.admin import SupportCategoryAdmin, SupportPriorityAdmin
from core.support_desk.models import SupportCategory, SupportPriority, SupportTicket
from core.support_desk.public import CreateTicketInput, create_ticket
from tests.factories import UserFactory


def _priority_form(**overrides):
    data = {
        "name": "High",
        "code": "",
        "rank": "2",
        "color_hex": "",
        "response_target_minutes": "",
        "resolution_target_minutes": "",
        "is_active": "on",
    }
    data.update(overrides)
    return {key: value for key, value in data.items() if value is not None}


def test_category_and_priority_are_registered():
    assert isinstance(admin.site._registry[SupportCategory], SupportCategoryAdmin)
    assert isinstance(admin.site._registry[SupportPriority], SupportPriorityAdmin)
    assert admin.site._registry[SupportCategory].actions is None
    assert admin.site._registry[SupportPriority].actions is None


@pytest.mark.django_db
def test_support_admin_sees_both_changelists(client, admin_user):
    client.force_login(admin_user)

    for name in ("supportcategory", "supportpriority"):
        assert client.get(reverse(f"admin:support_desk_{name}_changelist")).status_code == 200
        assert client.get(reverse(f"admin:support_desk_{name}_add")).status_code == 200


@pytest.mark.django_db
def test_staff_without_support_admin_role_is_denied_even_with_model_permissions(client):
    from django.contrib.auth.models import Permission

    staff = UserFactory(username="staff_only", is_staff=True)
    staff.user_permissions.add(*Permission.objects.filter(content_type__app_label="support_desk"))
    client.force_login(staff)

    assert client.get(reverse("admin:support_desk_supportcategory_changelist")).status_code == 403
    assert client.post(reverse("admin:support_desk_supportcategory_add"), {"name": "X"}).status_code == 403
    assert not SupportCategory.objects.filter(name="X").exists()


@pytest.mark.django_db
def test_add_category_goes_through_command_and_defaults_code(client, admin_user):
    client.force_login(admin_user)

    response = client.post(
        reverse("admin:support_desk_supportcategory_add"),
        {"name": "Network Access", "code": "", "description": "", "sort_order": "3", "is_active": "on"},
    )

    assert response.status_code == 302
    category = SupportCategory.objects.get(name="Network Access")
    assert category.code == "network-access"
    assert category.sort_order == 3


@pytest.mark.django_db
def test_change_category_clears_default_team(client, admin_user, support_setup):
    category = support_setup["category"]
    client.force_login(admin_user)

    response = client.post(
        reverse("admin:support_desk_supportcategory_change", args=[category.pk]),
        {"name": "Renamed", "code": category.code, "description": "", "sort_order": "0", "default_team": ""},
    )

    assert response.status_code == 302
    category.refresh_from_db()
    assert category.name == "Renamed"
    assert category.is_active is False
    assert category.default_team is None


@pytest.mark.django_db
def test_setting_a_default_priority_clears_the_previous_default(client, admin_user, support_setup):
    assert support_setup["priority_med"].is_default
    client.force_login(admin_user)

    response = client.post(
        reverse("admin:support_desk_supportpriority_add"), _priority_form(name="Urgent", rank="1", is_default="on")
    )

    assert response.status_code == 302
    assert list(SupportPriority.objects.filter(is_default=True).values_list("name", flat=True)) == ["Urgent"]
    assert SupportPriority.objects.get(name="Urgent").code == "urgent"


@pytest.mark.django_db
def test_priority_form_rejects_response_target_longer_than_resolution(client, admin_user):
    client.force_login(admin_user)

    response = client.post(
        reverse("admin:support_desk_supportpriority_add"),
        _priority_form(name="Odd", response_target_minutes="120", resolution_target_minutes="60"),
    )

    assert response.status_code == 200
    assert "response_target_minutes" in response.context["adminform"].form.errors
    assert not SupportPriority.objects.filter(name="Odd").exists()


@pytest.mark.django_db
@pytest.mark.parametrize(("field", "value"), [("color_hex", "red"), ("rank", "0"), ("resolution_target_minutes", "0")])
def test_priority_form_applies_api_validation(client, admin_user, field, value):
    client.force_login(admin_user)

    response = client.post(reverse("admin:support_desk_supportpriority_add"), _priority_form(**{field: value}))

    assert response.status_code == 200
    assert field in response.context["adminform"].form.errors


@pytest.mark.django_db
def test_change_priority_can_clear_sla_targets(client, admin_user, support_setup):
    priority = support_setup["priority_high"]
    SupportPriority.objects.filter(pk=priority.pk).update(response_target_minutes=30, resolution_target_minutes=60)
    client.force_login(admin_user)

    response = client.post(
        reverse("admin:support_desk_supportpriority_change", args=[priority.pk]),
        _priority_form(name=priority.name, code=priority.code, rank=str(priority.rank)),
    )

    assert response.status_code == 302
    priority.refresh_from_db()
    assert priority.response_target_minutes is None
    assert priority.resolution_target_minutes is None


@pytest.mark.django_db
def test_unused_category_can_be_deleted(client, admin_user):
    unused = SupportCategory.objects.create(name="Unused")
    client.force_login(admin_user)

    response = client.post(reverse("admin:support_desk_supportcategory_delete", args=[unused.pk]), {"post": "yes"})

    assert response.status_code == 302
    assert not SupportCategory.objects.filter(pk=unused.pk).exists()


@pytest.mark.django_db
def test_category_in_use_cannot_be_deleted(client, admin_user, requester_user, support_setup):
    ticket = create_ticket(
        CreateTicketInput(subject="Scope", description="Broken", category_id=support_setup["category"].pk),
        actor=requester_user,
    )
    client.force_login(admin_user)
    url = reverse("admin:support_desk_supportcategory_delete", args=[ticket.category_id])

    response = client.post(url, {"post": "yes"})

    assert response.status_code == 200  # Django lists the protected tickets instead of deleting.
    assert response.context["protected"]
    assert SupportTicket.objects.filter(pk=ticket.pk).exists()
    assert SupportCategory.objects.filter(pk=ticket.category_id).exists()
