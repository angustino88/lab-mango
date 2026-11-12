"""Bench and equipment bookings.

Booking status and approval status are separate state machines (AGENTS.md rule 2); both are shown and
filtered independently.
"""

from django.contrib import admin

from core.common.admin import LabMangoModelAdmin
from core.labs.models import BenchBooking, EquipmentBooking

_BOOKING_COLUMNS = ("starts_at", "ends_at", "status", "approval_status", "requester", "project")
_BOOKING_FILTERS = ("status", "approval_status", "starts_at")
_BOOKING_SEARCH = ("booking_code", "requester__username", "requester__email", "project__code")


@admin.register(BenchBooking)
class BenchBookingAdmin(LabMangoModelAdmin):
    list_display = ("booking_code", "bench", *_BOOKING_COLUMNS)
    list_select_related = ("bench", "requester", "project")
    list_filter = _BOOKING_FILTERS
    search_fields = (*_BOOKING_SEARCH, "bench__name", "bench__sku")
    autocomplete_fields = ("bench", "requester", "approved_by", "project")
    label_select_related = ("bench",)  # __str__ reads the bench (session-log autocomplete).


@admin.register(EquipmentBooking)
class EquipmentBookingAdmin(LabMangoModelAdmin):
    list_display = ("booking_code", "equipment", *_BOOKING_COLUMNS)
    list_select_related = ("equipment", "requester", "project")
    list_filter = _BOOKING_FILTERS
    search_fields = (*_BOOKING_SEARCH, "equipment__name", "equipment__sku")
    autocomplete_fields = ("equipment", "requester", "approved_by", "project")
    raw_id_fields = ("batch",)
