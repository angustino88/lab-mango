"""Django admin for users, URS groups and role mapping.

Roles are configured in one place: the URS group (URS id, name, Labs role). Saving a URS group creates and
names its Django group, which only stores membership written by URS sync. The Django group screen is shown
to superusers only.

Role-granting fields (``is_staff``, ``is_superuser``, ``is_urs_managed``, ``groups``, ``user_permissions``,
URS groups) are editable by superusers only. Every other staff user sees them read-only. Django admin
records each change in its log.
"""

import logging

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import admin as auth_admin
from django.contrib.auth import decorators, get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Count
from django.utils.translation import gettext_lazy as _

from core.users.access import LabsRole, effective_labs_roles
from core.users.forms import UserAdminChangeForm, UserAdminCreationForm
from core.users.models import EntraIdentity, LabManagementEmail, URSGroup
from core.users.public import ensure_urs_group_linked
from core.users.tasks import sync_selected_urs_groups

logger = logging.getLogger(__name__)

User = get_user_model()

if settings.DJANGO_ADMIN_FORCE_ALLAUTH:
    admin.site.login = decorators.login_required(admin.site.login)  # type: ignore[method-assign]

_ROLE_GRANTING_USER_FIELDS = ("is_staff", "is_superuser", "is_urs_managed", "groups", "user_permissions")


@admin.register(User)
class UserAdmin(auth_admin.UserAdmin):
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (_("Personal info"), {"fields": ("name", "email", "first_name", "last_name", "display_name", "department")}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "labs_roles",
                    "is_staff",
                    "is_superuser",
                    "is_urs_managed",
                    "groups",
                    "user_permissions",
                ),
                "description": _(
                    "Labs roles come from the URS groups the user belongs to. Activity is managed by URS sync."
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2"),
            },
        ),
    )
    list_display = ["username", "display_name", "is_superuser", "is_staff", "is_active", "is_urs_managed"]
    list_filter = ("is_active", "is_staff", "is_superuser", "is_urs_managed", "groups")
    search_fields = ["display_name", "username", "email"]
    readonly_fields = (*auth_admin.UserAdmin.readonly_fields, "is_active", "labs_roles")

    def get_readonly_fields(self, request, obj=None):
        fields = tuple(super().get_readonly_fields(request, obj))
        if request.user.is_superuser:
            return fields
        return (*fields, *_ROLE_GRANTING_USER_FIELDS)

    @admin.display(description=_("Labs roles"))
    def labs_roles(self, obj) -> str:
        if obj is None or obj.pk is None:
            return "-"
        roles = effective_labs_roles(obj)
        return ", ".join(role.value for role in LabsRole if role in roles) or "none"


class SuperuserManagedGroupAdmin(auth_admin.GroupAdmin):
    """Django groups are created by URS groups; only superusers see or change them."""

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


admin.site.unregister(Group)
admin.site.register(Group, SuperuserManagedGroupAdmin)


def _queue_sync(request, queryset, *, force: bool) -> None:
    ids = list(queryset.values_list("pk", flat=True))
    try:
        sync_selected_urs_groups.delay(ids, force=force)
    except Exception:
        logger.exception("Could not queue URS sync")
        messages.error(request, _("The sync could not be queued. Try again later or check the task queue."))
        return
    messages.success(
        request,
        _("Sync queued for %(count)d group(s). Refresh this page to see the result.") % {"count": len(ids)},
    )


@admin.register(URSGroup)
class URSGroupAdmin(admin.ModelAdmin):
    list_display = (
        "urs_group_name",
        "urs_group_id",
        "group",
        "labs_role",
        "active",
        "member_count",
        "last_sync_at",
        "last_sync_status",
        "last_sync_message",
    )
    list_editable = ("labs_role",)
    list_filter = ("labs_role", "active", "last_sync_status")
    search_fields = ("urs_group_name", "urs_group_id", "group__name")
    readonly_fields = ("group", "last_sync_at", "last_sync_status", "last_sync_message")
    fields = ("urs_group_name", "urs_group_id", "labs_role", "active", *readonly_fields)
    actions = ["queue_sync", "queue_forced_sync"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("group").annotate(_member_count=Count("group__user"))

    @admin.display(description=_("Members"), ordering="_member_count")
    def member_count(self, obj) -> int:
        return obj._member_count

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        ensure_urs_group_linked(urs_group_id=obj.pk)
        if obj.active:
            # Members follow URS immediately; the sync runs after this save commits.
            transaction.on_commit(lambda: _queue_sync(request, URSGroup.objects.filter(pk=obj.pk), force=False))

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not settings.URS_SYNC_SAFETY_BRAKE:
            # Without the safety check nothing is ever blocked, so there is nothing to force.
            actions.pop("queue_forced_sync", None)
        return actions

    @admin.action(description=_("Sync selected URS groups"), permissions=["change"])
    def queue_sync(self, request, queryset):
        _queue_sync(request, queryset, force=False)

    @admin.action(
        description=_("Sync selected URS groups and apply blocked removals"),
        permissions=["change"],
    )
    def queue_forced_sync(self, request, queryset):
        _queue_sync(request, queryset, force=True)


admin.site.register(LabManagementEmail, admin.ModelAdmin)


@admin.register(EntraIdentity)
class EntraIdentityAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant_id", "object_id", "created_at")
    readonly_fields = ("user", "tenant_id", "object_id", "created_at")
    autocomplete_fields = ("user",)

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser and obj is not None

    def has_delete_permission(self, request, obj=None):
        return False
