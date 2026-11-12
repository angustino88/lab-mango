"""Bench reference data (groups, types), benches and favorites."""

from django.contrib import admin

from core.common.admin import LabMangoModelAdmin
from core.labs.admin._base import ActiveNamedLookupAdmin
from core.labs.models import Bench, BenchFavorite, BenchGroup, BenchType

admin.site.register((BenchGroup, BenchType), ActiveNamedLookupAdmin)


@admin.register(Bench)
class BenchAdmin(LabMangoModelAdmin):
    list_display = (
        "name",
        "sku",
        "bench_group",
        "type",
        "setup_location",
        "lifecycle_status",
        "criticality",
        "department",
    )
    list_select_related = ("bench_group", "type", "setup_location", "department")
    list_filter = ("lifecycle_status", "bench_group", "type")
    search_fields = ("name", "sku", "setup_location__name")
    autocomplete_fields = ("owner", "department", "team", "bench_group", "type", "setup_location", "station_slot")
    readonly_fields = ("uid",)


@admin.register(BenchFavorite)
class BenchFavoriteAdmin(LabMangoModelAdmin):
    list_display = ("user", "bench", "created")
    list_select_related = ("user", "bench")
    search_fields = ("user__username", "user__email", "bench__name", "bench__sku")
    autocomplete_fields = ("user", "bench")
