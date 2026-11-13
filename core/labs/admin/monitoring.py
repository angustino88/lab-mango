"""Agent-reported activity, monitoring events, visits, storage and analytics observations.

All view-only: these rows are written by agents, ingestion commands and analytics tasks, never by hand.
"""

from django.contrib import admin

from core.common.admin import ReadOnlyModelAdmin
from core.labs.models import (
    ActiveLaboratoryObservation,
    ActiveUserObservation,
    BookingOutcomeObservation,
    BookingVolumeObservation,
    ComputingActivity,
    LaboratoryAvailabilityObservation,
    LaboratoryVisitEvent,
    LabSessionLog,
    MonitoringEvent,
    ProjectUsageObservation,
    ResourceUtilizationObservation,
    StorageQuotaMeasurement,
    VisitorVolumeObservation,
)


@admin.register(ComputingActivity)
class ComputingActivityAdmin(ReadOnlyModelAdmin):
    list_display = ("computing", "status", "remote_user", "booking_code", "last_agent_report_at", "offline_at")
    list_select_related = ("computing",)
    list_filter = ("status", "last_agent_report_at")
    search_fields = ("computing__name", "computing__sku", "remote_user", "remote_computer", "booking_code")
    autocomplete_fields = ("computing",)


@admin.register(LabSessionLog)
class LabSessionLogAdmin(ReadOnlyModelAdmin):
    list_display = (
        "host_name",
        "remote_user",
        "user",
        "bench",
        "access_type",
        "login_time",
        "logout_time",
        "active_duration_seconds",
    )
    list_select_related = ("user", "bench")
    list_filter = ("access_type", "login_time")
    search_fields = ("host_name", "remote_user", "remote_ip", "booking_code", "user__username")
    autocomplete_fields = ("computing_equipment", "booking", "bench", "user")


@admin.register(MonitoringEvent)
class MonitoringEventAdmin(ReadOnlyModelAdmin):
    list_display = ("occurred_at", "computer", "action", "action_name", "subject_type", "subject_name")
    list_select_related = ("computer",)
    list_filter = ("action", "occurred_at")
    search_fields = ("subject_name", "subject_id", "action_name", "agent_id", "computer__name")
    autocomplete_fields = ("computer",)


@admin.register(LaboratoryVisitEvent)
class LaboratoryVisitEventAdmin(ReadOnlyModelAdmin):
    list_display = ("occurred_at", "visitor", "source", "facility_identifier", "external_reference")
    list_select_related = ("visitor",)
    list_filter = ("source", "occurred_at")
    search_fields = ("external_reference", "facility_identifier", "visitor__username")
    autocomplete_fields = ("visitor",)


@admin.register(StorageQuotaMeasurement)
class StorageQuotaMeasurementAdmin(ReadOnlyModelAdmin):
    list_display = (
        "measured_at",
        "account_identifier",
        "account_display_name",
        "computer_identifier",
        "used_gibibytes",
        "quota_gibibytes",
        "source",
    )
    list_filter = ("source", "measured_at")
    search_fields = ("account_identifier", "account_display_name", "computer_identifier")


_OBSERVATION_BASE = ("period_start", "period_end", "granularity", "source", "recorded_at")
_OBSERVATION_SKIP = {"id", "created", "modified", *_OBSERVATION_BASE}


def _observation_admin(model):
    """Admin for one observation table: the period columns, then that table's measured values."""
    values = tuple(f.name for f in model._meta.concrete_fields if f.name not in _OBSERVATION_SKIP)
    return type(
        f"{model.__name__}Admin",
        (ReadOnlyModelAdmin,),
        {
            "__module__": __name__,
            "list_display": (*_OBSERVATION_BASE[:3], *values, "source"),
            "list_filter": ("granularity", "source", "period_start"),
        },
    )


for _model in (
    ActiveUserObservation,
    ActiveLaboratoryObservation,
    BookingVolumeObservation,
    BookingOutcomeObservation,
    VisitorVolumeObservation,
    ResourceUtilizationObservation,
    LaboratoryAvailabilityObservation,
    ProjectUsageObservation,
):
    admin.site.register(_model, _observation_admin(_model))
