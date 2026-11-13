"""Location reference data (country > city > building, station types) and rooms, stations, slots."""

from django.contrib import admin

from core.common.admin import LabMangoModelAdmin
from core.labs.admin._base import ROOM_LABEL_RELATED, NamedLookupAdmin, room_label_related
from core.labs.models import Building, City, Country, Room, RoomSlot, Station, StationSlot, StationType


@admin.register(Country)
class CountryAdmin(LabMangoModelAdmin):
    list_display = ("name", "code")
    search_fields = ("name", "code")
    ordering = ("name",)


@admin.register(City)
class CityAdmin(LabMangoModelAdmin):
    list_display = ("name", "country")
    list_select_related = ("country",)
    list_filter = ("country",)
    search_fields = ("name", "country__name", "country__code")
    ordering = ("country__name", "name")


@admin.register(Building)
class BuildingAdmin(LabMangoModelAdmin):
    list_display = ("name", "city", "country_name", "address")
    list_select_related = ("city__country",)
    list_filter = ("city__country", "city")
    search_fields = ("name", "address", "city__name")
    autocomplete_fields = ("city",)
    ordering = ("city__name", "name")

    @admin.display(description="Country", ordering="city__country__name")
    def country_name(self, obj):
        return obj.city.country.name if obj.city and obj.city.country else "-"


admin.site.register(StationType, NamedLookupAdmin)


@admin.register(Room)
class RoomAdmin(LabMangoModelAdmin):
    list_display = ("name", "sku", "building", "city", "floor", "department", "max_occupancy")
    list_select_related = (*ROOM_LABEL_RELATED, "department")
    # Building names repeat across cities, so buildings are searched, not offered as a filter.
    list_filter = ("country", "department")
    search_fields = ("name", "label", "sku", "building__name", "city__name")
    autocomplete_fields = ("owner", "department", "group", "country", "city", "building")
    readonly_fields = ("uid",)
    label_select_related = ROOM_LABEL_RELATED


@admin.register(RoomSlot)
class RoomSlotAdmin(LabMangoModelAdmin):
    list_display = ("slot_code", "room", "row_index", "col_index", "slot_type", "status", "is_accessible")
    list_select_related = room_label_related("room")
    list_filter = ("slot_type", "status", "is_accessible")
    search_fields = ("slot_code", "room__name", "room__label")
    autocomplete_fields = ("room",)
    label_select_related = room_label_related("room")


@admin.register(Station)
class StationAdmin(LabMangoModelAdmin):
    list_display = ("name", "label", "type", "room", "bench_capacity", "department")
    list_select_related = ("type", "department", *room_label_related("room"))
    list_filter = ("type", "department")
    search_fields = ("name", "label", "sku", "room__name")
    autocomplete_fields = ("owner", "department", "group", "type", "room", "slot")
    readonly_fields = ("uid",)


@admin.register(StationSlot)
class StationSlotAdmin(LabMangoModelAdmin):
    list_display = ("slot_code", "label", "station", "position_index", "status")
    list_select_related = ("station",)
    list_filter = ("status",)
    search_fields = ("slot_code", "label", "station__name")
    autocomplete_fields = ("station",)
    filter_horizontal = ("compatible_bench_types",)
    label_select_related = ("station",)
