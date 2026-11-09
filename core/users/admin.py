from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import admin as auth_admin
from django.contrib.auth import decorators, get_user_model
from django.utils.translation import gettext_lazy as _

from core.users.features.urs_sync.sync_group.service import sync_urs_group
from core.users.forms import UserAdminChangeForm, UserAdminCreationForm
from core.users.models import EntraIdentity, LabManagementEmail, URSGroup

User = get_user_model()

if settings.DJANGO_ADMIN_FORCE_ALLAUTH:
    admin.site.login = decorators.login_required(admin.site.login)  # type: ignore[method-assign]


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
                    "is_staff",
                    "is_superuser",
                    "is_urs_managed",
                    "groups",
                    "user_permissions",
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
    list_display = ["username", "display_name", "is_superuser", "is_active"]
    search_fields = ["display_name", "username", "email"]
    readonly_fields = (*auth_admin.UserAdmin.readonly_fields, "is_active")


def _sync_urs_groups_action(modeladmin, request, queryset):
    """Admin action: sync selected URS groups with Django groups."""
    try:
        sync_urs_group(queryset)
        messages.success(request, "Sync group(s) successfully.")
    except Exception as exc:
        messages.error(request, f"Sync group(s) failed: {exc}")


_sync_urs_groups_action.short_description = "Sync selected URS groups"  # type: ignore[attr-defined]


@admin.register(URSGroup)
class URSGroupAdmin(admin.ModelAdmin):
    list_display = ("urs_group_name", "urs_group_id", "group", "labs_role", "active")
    list_editable = ("labs_role",)
    list_filter = ("labs_role", "active")
    actions = [_sync_urs_groups_action]


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
