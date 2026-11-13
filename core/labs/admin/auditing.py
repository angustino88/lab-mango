"""Status history and audit trails for rooms, stations, equipment and resources.

All view-only: the feature commands append these records; editing one would rewrite history.
"""

from django.contrib import admin

from core.common.admin import ReadOnlyModelAdmin
from core.labs.admin._base import room_label_related
from core.labs.models import (
    EquipmentEvent,
    ResourceAudit,
    ResourceChangeLog,
    RoomStatusRecord,
    StationStatusRecord,
)


@admin.register(RoomStatusRecord)
class RoomStatusRecordAdmin(ReadOnlyModelAdmin):
    list_display = ("room", "status", "created", "creator")
    list_select_related = ("creator", *room_label_related("room"))
    list_filter = ("status", "created")
    search_fields = ("room__name", "room__label")
    autocomplete_fields = ("room",)


@admin.register(StationStatusRecord)
class StationStatusRecordAdmin(ReadOnlyModelAdmin):
    list_display = ("station", "status", "created", "creator")
    list_select_related = ("station", "creator")
    list_filter = ("status", "created")
    search_fields = ("station__name", "station__label")
    autocomplete_fields = ("station",)


@admin.register(EquipmentEvent)
class EquipmentEventAdmin(ReadOnlyModelAdmin):
    list_display = ("occurred_at", "equipment", "axis", "from_value", "to_value", "reason", "actor")
    list_select_related = ("equipment", "actor")
    list_filter = ("axis", "occurred_at")
    search_fields = ("equipment__name", "equipment__sku", "reason")
    autocomplete_fields = ("equipment", "actor")


@admin.register(ResourceAudit)
class ResourceAuditAdmin(ReadOnlyModelAdmin):
    list_display = ("audited_at", "resource_content_type", "resource_object_id", "result", "auditor")
    list_select_related = ("resource_content_type", "auditor")
    list_filter = ("result", "resource_content_type", "audited_at")
    search_fields = ("resource_object_id", "remarks", "auditor__username")
    autocomplete_fields = ("auditor",)


@admin.register(ResourceChangeLog)
class ResourceChangeLogAdmin(ReadOnlyModelAdmin):
    list_display = ("created", "resource_content_type", "resource_object_id", "action", "field_name", "creator")
    list_select_related = ("resource_content_type", "creator")
    list_filter = ("action", "resource_content_type", "created")
    search_fields = ("resource_object_id", "field_name")
