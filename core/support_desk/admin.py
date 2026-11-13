"""Support Desk Django admin: ticket categories and priorities.

Every write goes through the same application commands as the admin API (``manage_config``), so the
admin keeps the API's rules: support-admin authorization, default ``code`` from the name, a single default
priority, and response target <= resolution target. Django model permissions grant nothing here; only
support admins (Labs ``admin`` role or superuser) may add, change or delete.

Deleting a category or priority that tickets use is refused by Django's protected-objects check
(``SupportTicket`` uses ``on_delete=PROTECT``); deactivate it instead. Bulk actions are disabled so every
delete passes through that check and the command.
"""

from django import forms
from django.contrib import admin

from core.common.admin import LabMangoModelAdmin
from core.support_desk.features.tickets.application.policies import can_manage_configuration
from core.support_desk.features.tickets.public import (
    CreateCategoryInput,
    CreatePriorityInput,
    UpdateCategoryInput,
    UpdatePriorityInput,
    create_category,
    create_priority,
    delete_category,
    delete_priority,
    update_category,
    update_priority,
)
from core.support_desk.models import SupportCategory, SupportPriority


class _SupportConfigurationAdmin(LabMangoModelAdmin):
    """Support admins only; writes are delegated to the configuration commands."""

    actions = None
    readonly_fields = ("created_at", "updated_at")

    def has_module_permission(self, request) -> bool:
        return can_manage_configuration(request.user)

    def has_view_permission(self, request, obj=None) -> bool:
        return can_manage_configuration(request.user)

    def has_add_permission(self, request) -> bool:
        return can_manage_configuration(request.user)

    def has_change_permission(self, request, obj=None) -> bool:
        return can_manage_configuration(request.user)

    def has_delete_permission(self, request, obj=None) -> bool:
        return can_manage_configuration(request.user)

    @staticmethod
    def _copy_saved(obj, saved) -> None:
        # The admin redirects and logs using ``obj``; reflect what the command persisted.
        for field in obj._meta.concrete_fields:
            setattr(obj, field.attname, getattr(saved, field.attname))


class SupportPriorityAdminForm(forms.ModelForm):
    color_hex = forms.RegexField(
        regex=r"^(#[0-9A-Fa-f]{6})?$",
        required=False,
        max_length=7,
        help_text="Optional '#RRGGBB' badge colour.",
    )

    class Meta:
        model = SupportPriority
        fields = "__all__"

    def clean_rank(self):
        rank = self.cleaned_data["rank"]
        if rank < 1:
            raise forms.ValidationError("Rank must be 1 or higher.")
        return rank

    def clean(self):
        cleaned = super().clean() or {}
        for name in ("response_target_minutes", "resolution_target_minutes"):
            if cleaned.get(name) == 0:
                self.add_error(name, "Use a positive number of minutes, or leave empty for no target.")
        response = cleaned.get("response_target_minutes")
        resolution = cleaned.get("resolution_target_minutes")
        if response and resolution and response > resolution:
            self.add_error(
                "response_target_minutes", "The response target cannot be longer than the resolution target."
            )
        return cleaned


@admin.register(SupportCategory)
class SupportCategoryAdmin(_SupportConfigurationAdmin):
    list_display = ("name", "code", "default_team", "sort_order", "is_active", "updated_at")
    list_select_related = ("default_team",)
    list_filter = ("is_active",)
    search_fields = ("name", "code", "description")
    ordering = ("sort_order", "name", "id")
    fields = ("name", "code", "description", "default_team", "sort_order", "is_active", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        data = form.cleaned_data
        team = data.get("default_team")
        if change:
            saved = update_category(
                UpdateCategoryInput(
                    category_id=obj.pk,
                    name=data["name"],
                    code=data["code"],
                    description=data["description"],
                    sort_order=data["sort_order"],
                    is_active=data["is_active"],
                    default_team_id=team.pk if team else None,
                    clear_default_team=team is None,
                ),
                actor=request.user,
            )
        else:
            saved = create_category(
                CreateCategoryInput(
                    name=data["name"],
                    code=data["code"],
                    description=data["description"],
                    sort_order=data["sort_order"],
                    is_active=data["is_active"],
                    default_team_id=team.pk if team else None,
                ),
                actor=request.user,
            )
        self._copy_saved(obj, saved)

    def delete_model(self, request, obj):
        delete_category(obj.pk, actor=request.user)


@admin.register(SupportPriority)
class SupportPriorityAdmin(_SupportConfigurationAdmin):
    form = SupportPriorityAdminForm
    list_display = (
        "rank",
        "name",
        "code",
        "is_default",
        "is_active",
        "response_target_minutes",
        "resolution_target_minutes",
        "color_hex",
    )
    list_display_links = ("rank", "name")
    list_filter = ("is_active", "is_default")
    search_fields = ("name", "code")
    ordering = ("rank", "name", "id")
    fields = (
        "name",
        "code",
        "rank",
        "color_hex",
        "response_target_minutes",
        "resolution_target_minutes",
        "is_default",
        "is_active",
        "created_at",
        "updated_at",
    )

    def save_model(self, request, obj, form, change):
        data = form.cleaned_data
        response = data.get("response_target_minutes")
        resolution = data.get("resolution_target_minutes")
        if change:
            saved = update_priority(
                UpdatePriorityInput(
                    priority_id=obj.pk,
                    name=data["name"],
                    code=data["code"],
                    rank=data["rank"],
                    color_hex=data["color_hex"],
                    response_target_minutes=response,
                    resolution_target_minutes=resolution,
                    clear_response_target=response is None,
                    clear_resolution_target=resolution is None,
                    is_default=data["is_default"],
                    is_active=data["is_active"],
                ),
                actor=request.user,
            )
        else:
            saved = create_priority(
                CreatePriorityInput(
                    name=data["name"],
                    code=data["code"],
                    rank=data["rank"],
                    color_hex=data["color_hex"],
                    response_target_minutes=response,
                    resolution_target_minutes=resolution,
                    is_default=data["is_default"],
                    is_active=data["is_active"],
                ),
                actor=request.user,
            )
        self._copy_saved(obj, saved)

    def delete_model(self, request, obj):
        delete_priority(obj.pk, actor=request.user)
