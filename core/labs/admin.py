from django.contrib import admin
from django.db.models import Count

from core.labs.models import (
    ActiveLaboratoryObservation,
    ActiveUserObservation,
    Bench,
    BenchBooking,
    BenchFavorite,
    BenchGroup,
    BenchType,
    BookingOutcomeObservation,
    BookingVolumeObservation,
    Building,
    City,
    ComputingActivity,
    Equipment,
    EquipmentBooking,
    EquipmentEvent,
    LaboratoryAvailabilityObservation,
    LaboratoryVisitEvent,
    LabProject,
    LabSessionLog,
    MonitoringEvent,
    ProjectUsageObservation,
    PurchasePriority,
    ResourceAudit,
    ResourceChangeLog,
    ResourceUtilizationObservation,
    Room,
    RoomSlot,
    RoomStatusRecord,
    Station,
    StationSlot,
    StationStatusRecord,
    StorageQuotaMeasurement,
    VisitorVolumeObservation,
)
from core.labs.models.resource.equipment import (
    ComputingEquipment,
    EquipmentCategory,
    EquipmentKind,
    EquipmentManufacturer,
    EquipmentProductModel,
    EquipmentType,
    TechnicalUser,
)
from core.reference_data.admin import ProtectedReferenceAdmin


@admin.register(PurchasePriority)
class PurchasePriorityAdmin(ProtectedReferenceAdmin):
    list_display = ("code", "name", "rank", "is_active")
    list_editable = ("name", "rank", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")

# Models that use the default admin.
for model in (
    ActiveLaboratoryObservation,
    ActiveUserObservation,
    Bench,
    BenchBooking,
    BenchFavorite,
    BenchGroup,
    BenchType,
    BookingOutcomeObservation,
    BookingVolumeObservation,
    Building,
    City,
    ComputingActivity,
    ComputingEquipment,
    Equipment,
    EquipmentBooking,
    EquipmentEvent,
    LaboratoryAvailabilityObservation,
    LaboratoryVisitEvent,
    LabProject,
    LabSessionLog,
    MonitoringEvent,
    ProjectUsageObservation,
    ResourceAudit,
    ResourceChangeLog,
    ResourceUtilizationObservation,
    Room,
    RoomSlot,
    RoomStatusRecord,
    Station,
    StationSlot,
    StationStatusRecord,
    StorageQuotaMeasurement,
    TechnicalUser,
    VisitorVolumeObservation,
):
    admin.site.register(model)


# Equipment hierarchy: Category > Kind > Type, plus Manufacturer and ProductModel.
class EquipmentKindInline(admin.TabularInline):
    model = EquipmentKind
    extra = 0
    fields = ("name", "active")
    show_change_link = True


class EquipmentTypeInline(admin.TabularInline):
    model = EquipmentType
    extra = 0
    fields = ("name", "active")


@admin.register(EquipmentCategory)
class EquipmentCategoryAdmin(ProtectedReferenceAdmin):
    list_display = ("name", "kind_count", "active")
    search_fields = ("name",)
    inlines = [EquipmentKindInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_kinds=Count("kinds"))

    @admin.display(description="Kinds", ordering="_kinds")
    def kind_count(self, obj):
        return obj._kinds

@admin.register(EquipmentKind)
class EquipmentKindAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "type_count", "active")
    list_select_related = ("category",)
    list_filter = ("category", "active")
    search_fields = ("name", "category__name")
    inlines = [EquipmentTypeInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_types=Count("types"))

    @admin.display(description="Types", ordering="_types")
    def type_count(self, obj):
        return obj._types


@admin.register(EquipmentType)
class EquipmentTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "kind_name", "category_name", "active")
    list_select_related = ("kind__category",)
    list_filter = ("kind__category", "active")
    search_fields = ("name", "kind__name", "kind__category__name")
    autocomplete_fields = ("kind",)

    @admin.display(description="Kind", ordering="kind__name")
    def kind_name(self, obj):
        return obj.kind.name

    @admin.display(description="Category", ordering="kind__category__name")
    def category_name(self, obj):
        return obj.kind.category.name


@admin.register(EquipmentManufacturer)
class EquipmentManufacturerAdmin(admin.ModelAdmin):
    list_display = ("name", "category_list", "active")
    list_filter = ("categories", "active")
    search_fields = ("name",)
    filter_horizontal = ("categories",)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("categories")

    @admin.display(description="Categories")
    def category_list(self, obj):
        return ", ".join(c.name for c in obj.categories.all())


@admin.register(EquipmentProductModel)
class EquipmentProductModelAdmin(admin.ModelAdmin):
    list_display = ("name", "manufacturer", "type_name", "kind_name", "category_name", "active")
    list_select_related = ("manufacturer", "equipment_type__kind__category")
    list_filter = ("equipment_type__kind__category", "manufacturer", "active")
    search_fields = ("name", "manufacturer__name", "equipment_type__name")
    autocomplete_fields = ("manufacturer", "equipment_type")

    @admin.display(description="Type", ordering="equipment_type__name")
    def type_name(self, obj):
        return obj.equipment_type.name

    @admin.display(description="Kind", ordering="equipment_type__kind__name")
    def kind_name(self, obj):
        return obj.equipment_type.kind.name

    @admin.display(description="Category", ordering="equipment_type__kind__category__name")
    def category_name(self, obj):
        return obj.equipment_type.kind.category.name
