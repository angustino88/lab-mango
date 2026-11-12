"""Organisation reference data: departments, teams, projects, purchase priorities."""

from django.contrib import admin

from core.common.admin import LabMangoModelAdmin
from core.labs.admin._base import ActiveNamedLookupAdmin
from core.labs.models import Department, LabProject, PurchasePriority, Team, TechnicalUser
from core.reference_data.admin import ProtectedReferenceAdmin

admin.site.register(Department, ActiveNamedLookupAdmin)


@admin.register(Team)
class TeamAdmin(LabMangoModelAdmin):
    list_display = ("name", "department", "active", "modified")
    list_select_related = ("department",)
    list_filter = ("department", "active")
    search_fields = ("name", "description", "department__name")
    autocomplete_fields = ("department",)
    ordering = ("department__name", "name")


@admin.register(LabProject)
class LabProjectAdmin(LabMangoModelAdmin):
    list_display = ("code", "project_name", "owner", "starts_on", "ends_on", "active")
    list_select_related = ("owner",)
    list_filter = ("active",)
    search_fields = ("code", "project_name", "owner__username", "owner__email")
    autocomplete_fields = ("owner",)


@admin.register(PurchasePriority)
class PurchasePriorityAdmin(ProtectedReferenceAdmin):
    list_display = ("code", "name", "rank", "is_active")
    list_editable = ("name", "rank", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(TechnicalUser)
class TechnicalUserAdmin(LabMangoModelAdmin):
    list_display = ("username", "modified")
    search_fields = ("username",)
    ordering = ("username",)
