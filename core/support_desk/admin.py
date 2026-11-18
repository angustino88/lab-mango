"""Django admin for ticket categories, priorities and statuses.

All three are admin-defined configuration. Saves go through the application commands (which enforce the
support-admin policy and the single-default rule), and the screens are visible to support admins only.
Rows are deactivated rather than deleted because tickets reference them.
"""

from django import forms
from django.contrib import admin

from core.support_desk.exceptions import SupportDeskError
from core.support_desk.features.tickets.public import (
    CreateCategoryInput,
    CreatePriorityInput,
    CreateStatusInput,
    UpdateCategoryInput,
    UpdatePriorityInput,
    UpdateStatusInput,
    can_manage_configuration,
    create_category,
    create_priority,
    create_status,
    update_category,
    update_priority,
    update_status,
    validate_status_flags,
)
from core.support_desk.models import SupportCategory, SupportPriority, SupportStatus


class _SupportConfigAdmin(admin.ModelAdmin):
    """Shared policy: support admins only, no deletion, saves via application commands."""

    list_per_page = 50
    show_full_result_count = False

    def has_module_permission(self, request) -> bool:
        return can_manage_configuration(request.user)

    def has_view_permission(self, request, obj=None) -> bool:
        return can_manage_configuration(request.user)

    def has_add_permission(self, request) -> bool:
        return can_manage_configuration(request.user)

    def has_change_permission(self, request, obj=None) -> bool:
        return can_manage_configuration(request.user)

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def get_actions(self, request):
        return {}


@admin.register(SupportCategory)
class SupportCategoryAdmin(_SupportConfigAdmin):
    list_display = ("name", "code", "default_team", "is_active", "sort_order")
    list_filter = ("is_active",)
    list_select_related = ("default_team",)
    search_fields = ("name", "code")
    ordering = ("sort_order", "name", "id")
    fields = ("name", "code", "description", "default_team", "is_active", "sort_order")

    def save_model(self, request, obj, form, change) -> None:
        d = form.cleaned_data
        team = d.get("default_team")
        if change:
            saved = update_category(
                UpdateCategoryInput(
                    category_id=obj.pk,
                    name=d["name"],
                    description=d.get("description") or "",
                    sort_order=d.get("sort_order") or 0,
                    is_active=d.get("is_active", False),
                    code=d.get("code") or "",
                    default_team_id=team.pk if team else None,
                    clear_default_team=team is None,
                ),
                actor=request.user,
            )
        else:
            saved = create_category(
                CreateCategoryInput(
                    name=d["name"],
                    description=d.get("description") or "",
                    sort_order=d.get("sort_order") or 0,
                    is_active=d.get("is_active", False),
                    code=d.get("code") or "",
                    default_team_id=team.pk if team else None,
                ),
                actor=request.user,
            )
        obj.pk = saved.pk
        obj.refresh_from_db()


class SupportPriorityAdminForm(forms.ModelForm):
    class Meta:
        model = SupportPriority
        fields = "__all__"

    def clean(self):
        cleaned = super().clean() or {}
        response = cleaned.get("response_target_minutes")
        resolution = cleaned.get("resolution_target_minutes")
        if response is not None and resolution is not None and response > resolution:
            raise forms.ValidationError("The response target cannot be longer than the resolution target.")
        return cleaned


@admin.register(SupportPriority)
class SupportPriorityAdmin(_SupportConfigAdmin):
    form = SupportPriorityAdminForm
    list_display = ("name", "code", "rank", "color_hex", "is_default", "is_active")
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
    )

    def save_model(self, request, obj, form, change) -> None:
        d = form.cleaned_data
        response = d.get("response_target_minutes")
        resolution = d.get("resolution_target_minutes")
        if change:
            saved = update_priority(
                UpdatePriorityInput(
                    priority_id=obj.pk,
                    name=d["name"],
                    rank=d["rank"],
                    is_default=d.get("is_default", False),
                    is_active=d.get("is_active", False),
                    code=d.get("code") or "",
                    color_hex=d.get("color_hex") or "",
                    response_target_minutes=response,
                    resolution_target_minutes=resolution,
                    clear_response_target=response is None,
                    clear_resolution_target=resolution is None,
                ),
                actor=request.user,
            )
        else:
            saved = create_priority(
                CreatePriorityInput(
                    name=d["name"],
                    rank=d["rank"],
                    is_default=d.get("is_default", False),
                    is_active=d.get("is_active", False),
                    code=d.get("code") or "",
                    color_hex=d.get("color_hex") or "",
                    response_target_minutes=response,
                    resolution_target_minutes=resolution,
                ),
                actor=request.user,
            )
        obj.pk = saved.pk
        obj.refresh_from_db()


class SupportStatusAdminForm(forms.ModelForm):
    class Meta:
        model = SupportStatus
        fields = "__all__"

    def clean(self):
        cleaned = super().clean() or {}
        system_state = cleaned.get("system_state")
        if system_state:
            try:
                validate_status_flags(
                    system_state,
                    is_final=bool(cleaned.get("is_final")),
                    is_initial=bool(cleaned.get("is_initial")),
                    pauses_sla=bool(cleaned.get("pauses_sla")),
                )
            except SupportDeskError as exc:
                raise forms.ValidationError(str(exc)) from exc
        return cleaned


@admin.register(SupportStatus)
class SupportStatusAdmin(_SupportConfigAdmin):
    """Workflow statuses. Names are labels; behaviour comes from the fixed system state and flags.

    Allowed transitions between statuses are managed through ``/api/support/admin/transitions``.
    """

    form = SupportStatusAdminForm
    list_display = ("name", "system_state", "is_initial", "is_final", "pauses_sla", "is_active", "sort_order")
    list_filter = ("system_state", "is_active")
    search_fields = ("name",)
    ordering = ("sort_order", "id")
    fields = ("name", "system_state", "color_hex", "is_initial", "is_final", "pauses_sla", "is_active", "sort_order")

    def save_model(self, request, obj, form, change) -> None:
        d = form.cleaned_data
        values = {
            "name": d["name"],
            "system_state": d["system_state"],
            "is_initial": d.get("is_initial", False),
            "is_final": d.get("is_final", False),
            "pauses_sla": d.get("pauses_sla", False),
            "is_active": d.get("is_active", False),
            "sort_order": d.get("sort_order") or 0,
            "color_hex": d.get("color_hex") or "",
        }
        if change:
            saved = update_status(UpdateStatusInput(status_id=obj.pk, **values), actor=request.user)
        else:
            saved = create_status(CreateStatusInput(**values), actor=request.user)
        obj.pk = saved.pk
        obj.refresh_from_db()
