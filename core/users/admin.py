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
import re
from typing import Any

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import admin as auth_admin
from django.contrib.auth import decorators, get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.timesince import timesince
from django.utils.translation import gettext_lazy as _

from core.users.access import LabsRole
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


# ----------------------------------------------------------------------------------------------
# Presentation helpers (display only; no access decisions are made here)

_ROLE_LABELS = {"admin": _("Lab admin"), "coord": _("Lab coordinator"), "user": _("Lab user"), "": _("No role")}
_ROLE_COLORS = {"admin": "#b42318", "coord": "#175cd3", "user": "#067647", "": "#667085", "superuser": "#6941c6"}
_ROLE_RIGHTS = (
    ("admin", _("Everything a coordinator can do, plus the user directory (groups and members).")),
    (
        "coord",
        _(
            "Manages benches, equipment, licenses, rooms and monitoring; procurement, expenses and finance "
            "reports; approves other people's bookings."
        ),
    ),
    ("user", _("Reads the dashboard and the leaderboard; creates and changes their own bookings.")),
    ("", _("Grants nothing. Members without any other role cannot use Labs.")),
)
_SYNC_ICONS = {"applied": ("✔", "#067647"), "blocked": ("⏸", "#b54708"), "failed": ("✖", "#b42318")}


def _badge(label, color: str):
    return format_html(
        '<span style="display:inline-block;padding:1px 8px;border-radius:10px;background:{};color:#fff;'
        'font-size:11px;font-weight:600;white-space:nowrap">{}</span>',
        color,
        label,
    )


def _role_badge(role: str):
    return _badge(_ROLE_LABELS.get(role, role), _ROLE_COLORS.get(role, "#667085"))


def _ago(moment) -> str:
    return _("%(time)s ago") % {"time": timesince(moment).split(",")[0]} if moment else "-"


def _readable_sync_message(message: str) -> str:
    """``"+3 -1 (forced)"`` -> ``"3 added, 1 removed (forced)"``; other messages unchanged."""
    match = re.match(r"^\+(\d+) -(\d+)(.*)$", message or "")
    if not match:
        return message
    added, removed, rest = match.groups()
    return _("%(added)s added, %(removed)s removed") % {"added": added, "removed": removed} + rest


def _relabel(form, labels: dict, help_texts: dict | None = None):
    for name, label in labels.items():
        if name in form.base_fields:
            form.base_fields[name].label = label
    for name, text in (help_texts or {}).items():
        if name in form.base_fields:
            form.base_fields[name].help_text = text
    return form


def _role_groups(user) -> list:
    """URS groups of ``user`` from prefetched ``groups__ursgroup`` (no extra query)."""
    return [group.ursgroup for group in user.groups.all() if getattr(group, "ursgroup", None) is not None]


def _with_role_groups(queryset):
    return queryset.prefetch_related(Prefetch("groups", queryset=Group.objects.select_related("ursgroup")))


class LabsRoleFilter(admin.SimpleListFilter):
    title = _("Labs role")
    parameter_name = "labs_role"

    def lookups(self, request, model_admin):
        return (
            ("admin", _("Lab admin")),
            ("coord", _("Lab coordinator")),
            ("user", _("Lab user")),
            ("none", _("No role")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value in {"admin", "coord", "user"}:
            return queryset.filter(groups__ursgroup__labs_role=value).distinct()
        if value == "none":
            return queryset.exclude(groups__ursgroup__labs_role__in=["admin", "coord", "user"]).exclude(
                is_superuser=True
            )
        return queryset


@admin.register(User)
class UserAdmin(auth_admin.UserAdmin):
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm
    fieldsets = (
        (_("Profile"), {"fields": ("username", "display_name", "email", "department")}),
        (
            _("Access"),
            {
                "fields": ("access_summary", "is_active", "entra_status", "last_login", "date_joined"),
                "description": _(
                    "Labs roles come from the URS groups this person belongs to; change a role on the URS "
                    "group, not here. Membership and activity are kept in step with URS by the sync."
                ),
            },
        ),
        (
            _("Admin rights"),
            {
                "fields": ("is_staff", "is_superuser", "is_urs_managed"),
                "description": _(
                    "Staff can open this admin site. Superusers can do everything. Untick “URS-managed” only "
                    "for local accounts that URS must never change."
                ),
            },
        ),
        (
            _("Advanced: Django groups and permissions"),
            {
                "classes": ("collapse",),
                "fields": ("groups", "user_permissions"),
                "description": _(
                    "Group membership is written by URS sync. Direct Django permissions are rarely needed."
                ),
            },
        ),
        (_("Legacy fields"), {"classes": ("collapse",), "fields": ("name", "first_name", "last_name", "password")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2"),
                "description": _(
                    "Usually not needed: URS sync creates accounts. Create one here only for a local account; "
                    "leave the password empty for people who sign in with Microsoft."
                ),
            },
        ),
    )
    list_display = [
        "username",
        "display_name",
        "email",
        "role_badges",
        "urs_groups",
        "is_active",
        "last_seen",
        "entra_linked",
    ]
    list_filter = ("is_active", "is_urs_managed", "is_staff", "is_superuser")
    search_fields = ["display_name", "username", "email", "groups__name"]
    readonly_fields = (
        *auth_admin.UserAdmin.readonly_fields,
        "is_active",
        "access_summary",
        "entra_status",
        "last_login",
        "date_joined",
    )
    list_per_page = 50

    def get_list_filter(self, request):
        return (LabsRoleFilter, *self.list_filter)

    def get_form(self, request, obj=None, change=False, **kwargs):
        return _relabel(
            super().get_form(request, obj, change=change, **kwargs),
            {
                "is_staff": _("Staff (can open this admin site)"),
                "is_superuser": _("Superuser"),
                "is_urs_managed": _("URS-managed"),
            },
            {"is_urs_managed": _("URS sync keeps this account's groups and activity in step with URS.")},
        )

    def get_queryset(self, request):
        return _with_role_groups(super().get_queryset(request).select_related("entra_identity"))

    @admin.display(description=_("Labs roles"))
    def role_badges(self, user):
        if user.is_superuser:
            return _badge(_("Superuser"), _ROLE_COLORS["superuser"])
        roles = sorted({g.labs_role for g in _role_groups(user) if g.labs_role}, key=["admin", "coord", "user"].index)
        if not roles:
            return _role_badge("")
        return format_html_join(" ", "{}", ((_role_badge(role),) for role in roles))

    @admin.display(description=_("URS groups"))
    def urs_groups(self, user):
        groups = _role_groups(user)
        if not groups:
            return "-"
        return format_html_join(
            ", ",
            '<a href="{}">{}</a>',
            ((reverse("admin:users_ursgroup_change", args=[g.pk]), str(g)) for g in groups),
        )

    @admin.display(description=_("Last sign-in"), ordering="last_login")
    def last_seen(self, user) -> str:
        return _ago(user.last_login) if user.last_login else _("never")

    @admin.display(description=_("Microsoft linked"), boolean=True)
    def entra_linked(self, user) -> bool:
        return hasattr(user, "entra_identity")

    @admin.display(description=_("Labs access"))
    def access_summary(self, user):
        if user is None or user.pk is None:
            return "-"
        if user.is_superuser:
            return format_html("{} {}", _badge(_("Superuser"), _ROLE_COLORS["superuser"]), _("holds every role."))
        rows = [(g, g.labs_role) for g in _role_groups(user)]
        if not rows:
            return format_html("{} {}", _role_badge(""), _("Not in any URS group."))
        return format_html_join(
            format_html("<br>"),
            '{} <span style="color:var(--body-quiet-color)">from</span> <a href="{}">{}</a>',
            ((_role_badge(role), reverse("admin:users_ursgroup_change", args=[g.pk]), str(g)) for g, role in rows),
        )

    @admin.display(description=_("Microsoft account"))
    def entra_status(self, user):
        identity = getattr(user, "entra_identity", None) if user and user.pk else None
        if identity is None:
            return _("Not linked yet: linked automatically at the first Microsoft sign-in.")
        return format_html("{} <code>{}</code> ({})", _("Linked"), identity.object_id, _ago(identity.created_at))

    def get_readonly_fields(self, request, obj=None):
        fields = tuple(super().get_readonly_fields(request, obj))
        if request.user.is_superuser:
            return fields
        return (*fields, *_ROLE_GRANTING_USER_FIELDS)

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

    list_display = ("name", "urs_group", "role", "member_count")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("ursgroup").annotate(_member_count=Count("user"))

    @admin.display(description=_("URS group"))
    def urs_group(self, group):
        urs_group = getattr(group, "ursgroup", None)
        if urs_group is None:
            return _("— not linked to URS —")
        return format_html(
            '<a href="{}">{}</a>', reverse("admin:users_ursgroup_change", args=[urs_group.pk]), urs_group
        )

    @admin.display(description=_("Labs role"))
    def role(self, group):
        urs_group = getattr(group, "ursgroup", None)
        return _role_badge(urs_group.labs_role) if urs_group is not None else "-"

    @admin.display(description=_("Members"), ordering="_member_count")
    def member_count(self, group) -> int:
        return group._member_count

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
    list_display = ("urs_group_name", "urs_group_id", "role_badge", "active", "members_link", "sync_state")
    list_display_links = ("urs_group_name",)
    list_filter = ("labs_role", "active", "last_sync_status")
    search_fields = ("urs_group_name", "urs_group_id", "group__name")
    ordering = ("urs_group_name",)
    readonly_fields = ("role_rights", "members_table", "sync_state", "group")
    fieldsets = (
        (
            _("URS group"),
            {
                "fields": ("urs_group_name", "urs_group_id", "active"),
                "description": _(
                    "Copy the service ID from URS. Saving an active group syncs its members from URS right away."
                ),
            },
        ),
        (_("Labs role for every member"), {"fields": ("labs_role", "role_rights")}),
        (_("Members (from URS, read-only)"), {"fields": ("members_table",)}),
        (_("Last sync"), {"fields": ("sync_state", "group")}),
    )
    actions = ["queue_sync", "queue_forced_sync"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("group").annotate(_member_count=Count("group__user"))

    def get_readonly_fields(self, request, obj=None):
        fields = tuple(super().get_readonly_fields(request, obj))
        return fields if obj is not None else ("role_rights",)

    def get_fieldsets(self, request, obj=None):
        if obj is None:  # adding: nothing to show about members or sync yet
            return self.fieldsets[:2]
        return self.fieldsets

    def get_form(self, request, obj=None, change=False, **kwargs):
        return _relabel(
            super().get_form(request, obj, change=change, **kwargs),
            {"urs_group_name": _("Name"), "urs_group_id": _("URS service ID"), "labs_role": _("Labs role")},
            {
                "labs_role": _("Every member of this URS group gets this role. Empty grants nothing."),
                "active": _("Only active groups are synced on schedule."),
            },
        )

    @admin.display(description=_("Labs role"), ordering="labs_role")
    def role_badge(self, obj):
        return _role_badge(obj.labs_role)

    @admin.display(description=_("Members"), ordering="_member_count")
    def members_link(self, obj):
        count = getattr(obj, "_member_count", 0)
        if not obj.group_id or not count:
            return count
        url = reverse("admin:users_user_changelist") + f"?groups__id__exact={obj.group_id}"
        return format_html('<a href="{}">{}</a>', url, count)

    @admin.display(description=_("Last sync"))
    def sync_state(self, obj):
        if not obj.last_sync_status:
            return format_html('<span style="color:var(--body-quiet-color)">{}</span>', _("not synced yet"))
        icon, color = _SYNC_ICONS.get(obj.last_sync_status, ("•", "#667085"))
        return format_html(
            '<span style="color:{};font-weight:600">{} {}</span> · {} <span style="color:var(--body-quiet-color)">{}</span>',
            color,
            icon,
            obj.get_last_sync_status_display(),
            _ago(obj.last_sync_at),
            _readable_sync_message(obj.last_sync_message),
        )

    @admin.display(description=_("What this role can do"))
    def role_rights(self, obj):
        return format_html(
            "<table>{}</table>",
            format_html_join(
                "",
                "<tr><td style='padding:2px 12px 2px 0'>{}</td><td>{}</td></tr>",
                ((_role_badge(role), text) for role, text in _ROLE_RIGHTS),
            ),
        )

    @admin.display(description=_("Members"))
    def members_table(self, obj):
        if obj is None or not obj.group_id:
            return "-"
        total = getattr(obj, "_member_count", None)
        members = list(obj.group.user_set.order_by("username")[:200])
        if not members:
            return _("No members yet. They appear after the next successful sync.")
        rows = format_html_join(
            "",
            "<tr><td><a href='{}'>{}</a></td><td>{}</td><td>{}</td><td>{}</td></tr>",
            (
                (
                    reverse("admin:users_user_change", args=[member.pk]),
                    member.username,
                    member.display_name or "-",
                    _("active") if member.is_active else _("inactive"),
                    _ago(member.last_login) if member.last_login else _("never signed in"),
                )
                for member in members
            ),
        )
        more = ""
        if total and total > len(members):
            url = reverse("admin:users_user_changelist") + f"?groups__id__exact={obj.group_id}"
            more = format_html(
                '<p><a href="{}">{}</a></p>', url, _("Showing 200 of %(total)s. See all members") % {"total": total}
            )
        return format_html(
            "<table style='min-width:560px'><thead><tr><th>{}</th><th>{}</th><th>{}</th><th>{}</th></tr></thead>"
            "<tbody>{}</tbody></table>{}",
            _("Username"),
            _("Name"),
            _("Status"),
            _("Last sign-in"),
            rows,
            more,
        )

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
