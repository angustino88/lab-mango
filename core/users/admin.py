"""Django admin for users, URS groups and role mapping.

Roles are configured in one place: the URS group (URS id, name, Labs role). Saving a URS group creates and
names its Django group, which only stores membership written by URS sync. The Django group screen is shown
to superusers only.

Role-granting fields (``is_staff``, ``is_superuser``, ``is_urs_managed``, ``groups``, ``user_permissions``,
URS groups) are editable by superusers only. Every other staff user sees them read-only. Django admin
records each change in its log.
"""

import csv
import logging
from typing import Any

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import admin as auth_admin
from django.contrib.auth import decorators, get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _

from core.users.access import LabsRole, effective_labs_roles
from core.users.audit import diff, record_role_event
from core.users.forms import UserAdminChangeForm, UserAdminCreationForm
from core.users.models import EntraIdentity, LabManagementEmail, PrivilegedUser, RoleAuditEvent, URSGroup
from core.users.public import ensure_urs_group_linked
from core.users.tasks import sync_selected_urs_groups

logger = logging.getLogger(__name__)

User = get_user_model()

if settings.DJANGO_ADMIN_FORCE_ALLAUTH:
    admin.site.login = decorators.login_required(admin.site.login)  # type: ignore[method-assign]

_ROLE_GRANTING_USER_FIELDS = ("is_staff", "is_superuser", "is_urs_managed", "groups", "user_permissions")
_URS_GROUP_AUDIT_FIELDS = ("urs_group_name", "urs_group_id", "labs_role", "active")
# A new account starts with model defaults; only privileges granted on creation are recorded.
_NEW_USER_PRIVILEGES = {
    "is_staff": False,
    "is_superuser": False,
    "is_urs_managed": True,
    "groups": [],
    "user_permissions": [],
}


def _privilege_snapshot(user) -> dict[str, Any]:
    """Role-relevant state of a saved user, read from the database."""
    if user is None or user.pk is None:
        return {}
    row: dict[str, Any] = dict(
        User.objects.filter(pk=user.pk).values("is_staff", "is_superuser", "is_urs_managed").first() or {}
    )
    row["groups"] = sorted(Group.objects.filter(user__pk=user.pk).values_list("name", flat=True))
    row["user_permissions"] = sorted(
        f"{app}.{codename}"
        for app, codename in User.user_permissions.through.objects.filter(user_id=user.pk).values_list(
            "permission__content_type__app_label", "permission__codename"
        )
    )
    return row


def _group_permission_snapshot(group) -> list[str]:
    if group is None or group.pk is None:
        return []
    return sorted(
        f"{app}.{codename}" for app, codename in group.permissions.values_list("content_type__app_label", "codename")
    )


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

    def save_model(self, request, obj, form, change):
        obj._audit_before = _privilege_snapshot(obj) if change else dict(_NEW_USER_PRIVILEGES)
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        user = form.instance
        before = getattr(user, "_audit_before", {})
        changes = diff(before, _privilege_snapshot(user), _ROLE_GRANTING_USER_FIELDS)
        if changes:
            record_role_event(
                RoleAuditEvent.EventType.USER_PRIVILEGES_CHANGED,
                actor=request.user,
                target=user,
                changes=changes,
            )


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

    def save_model(self, request, obj, form, change):
        obj._audit_before = _group_permission_snapshot(obj) if change else []
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        group = form.instance
        before, after = getattr(group, "_audit_before", []), _group_permission_snapshot(group)
        if before != after:
            record_role_event(
                RoleAuditEvent.EventType.GROUP_PERMISSIONS_CHANGED,
                actor=request.user,
                subject=group.name,
                changes={"permissions": {"before": before, "after": after}},
            )


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
        before = (
            URSGroup.objects.filter(pk=obj.pk).values(*_URS_GROUP_AUDIT_FIELDS).first() if change else None
        ) or {}
        super().save_model(request, obj, form, change)
        ensure_urs_group_linked(urs_group_id=obj.pk)
        after = {name: getattr(obj, name) for name in _URS_GROUP_AUDIT_FIELDS}
        changes = diff(before, after, _URS_GROUP_AUDIT_FIELDS)
        if changes:
            record_role_event(
                RoleAuditEvent.EventType.URS_GROUP_CHANGED if change else RoleAuditEvent.EventType.URS_GROUP_CREATED,
                actor=request.user,
                subject=str(obj),
                changes=changes,
            )
        if obj.active:
            # Members follow URS immediately; the sync runs after this save commits.
            transaction.on_commit(lambda: _queue_sync(request, URSGroup.objects.filter(pk=obj.pk), force=False))

    def delete_model(self, request, obj):
        self._audit_deleted(request, [obj])
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        self._audit_deleted(request, list(queryset))
        super().delete_queryset(request, queryset)

    @staticmethod
    def _audit_deleted(request, urs_groups) -> None:
        for urs_group in urs_groups:
            record_role_event(
                RoleAuditEvent.EventType.URS_GROUP_DELETED,
                actor=request.user,
                subject=str(urs_group),
                changes={
                    name: {"before": getattr(urs_group, name), "after": None} for name in _URS_GROUP_AUDIT_FIELDS
                },
            )

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


@admin.register(RoleAuditEvent)
class RoleAuditEventAdmin(admin.ModelAdmin):
    """Read-only history of role and privilege changes; the database rejects edits and deletions."""

    list_display = ("occurred_at", "event_type", "actor_label", "target_label", "subject", "changes")
    list_filter = ("event_type", "occurred_at")
    search_fields = ("actor_label", "target_label", "subject")
    date_hierarchy = "occurred_at"
    readonly_fields = [field.name for field in RoleAuditEvent._meta.fields]

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


_PRIVILEGED_ROLES = (LabsRole.ADMIN.value, LabsRole.COORDINATOR.value)


class PrivilegeFilter(admin.SimpleListFilter):
    title = _("privilege")
    parameter_name = "privilege"

    def lookups(self, request, model_admin):
        return (
            ("superuser", _("Superuser")),
            ("admin", _("Lab admin")),
            ("coord", _("Lab coordinator")),
            ("staff", _("Staff")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "superuser":
            return queryset.filter(is_superuser=True)
        if value == "staff":
            return queryset.filter(is_staff=True)
        if value in _PRIVILEGED_ROLES:
            return queryset.filter(groups__ursgroup__labs_role=value).distinct()
        return queryset


@admin.register(PrivilegedUser)
class AccessReviewAdmin(admin.ModelAdmin):
    """Who holds elevated access, through which URS group, and when they last signed in (ISO 27001 A.5.18)."""

    list_display = (
        "username",
        "display_name",
        "privileges",
        "granted_by",
        "is_active",
        "last_login",
        "entra_linked",
    )
    list_filter = (PrivilegeFilter, "is_active")
    search_fields = ("username", "display_name", "email")
    ordering = ("username",)
    actions = ["export_csv"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(Q(is_superuser=True) | Q(is_staff=True) | Q(groups__ursgroup__labs_role__in=_PRIVILEGED_ROLES))
            .distinct()
            .select_related("entra_identity")
            .prefetch_related(Prefetch("groups", queryset=Group.objects.select_related("ursgroup")))
        )

    @staticmethod
    def _role_groups(user) -> list[tuple[str, str]]:
        rows = []
        for group in user.groups.all():
            urs_group = getattr(group, "ursgroup", None)
            if urs_group is not None and urs_group.labs_role in _PRIVILEGED_ROLES:
                rows.append((urs_group.labs_role, str(urs_group)))
        return sorted(rows)

    @admin.display(description=_("Privileges"))
    def privileges(self, user) -> str:
        labels = []
        if user.is_superuser:
            labels.append("superuser")
        labels.extend(role for role in _PRIVILEGED_ROLES if any(r == role for r, _ in self._role_groups(user)))
        if user.is_staff:
            labels.append("staff")
        return ", ".join(labels)

    @admin.display(description=_("Granted by URS group"))
    def granted_by(self, user) -> str:
        return "; ".join(f"{name} ({role})" for role, name in self._role_groups(user)) or "-"

    @admin.display(description=_("Entra linked"), boolean=True)
    def entra_linked(self, user) -> bool:
        return hasattr(user, "entra_identity")

    @admin.action(description=_("Export selected to CSV"))
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="access-review.csv"'
        writer = csv.writer(response)
        writer.writerow(
            ["username", "display_name", "privileges", "granted_by", "is_active", "last_login", "entra_linked"]
        )
        for user in self.get_queryset(request).filter(pk__in=queryset.values("pk")):
            writer.writerow(
                [
                    user.username,
                    user.display_name,
                    self.privileges(user),
                    self.granted_by(user),
                    user.is_active,
                    user.last_login.isoformat() if user.last_login else "",
                    self.entra_linked(user),
                ]
            )
        return response

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
