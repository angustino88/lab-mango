"""Equipment catalog (Category > Kind > Type, manufacturers, product models, lookups) and equipment."""

from django.contrib import admin
from django.db.models import Count

from core.common.admin import LabMangoModelAdmin
from core.labs.admin._base import NamedLookupAdmin
from core.labs.models import (
    ComputingProfile,
    Equipment,
    EquipmentCategory,
    EquipmentInterface,
    EquipmentKind,
    EquipmentManufacturer,
    EquipmentProductModel,
    EquipmentType,
    Material,
    ProductModelSpecification,
    SpecificationDefinition,
)
from core.labs.models.resource.equipment.display import DisplayResolution, DisplaySize
from core.labs.models.resource.equipment.networking import NetworkingProtocol
from core.labs.models.resource.equipment.sample import SampleCharacteristic, SampleCustomer
from core.reference_data.admin import ProtectedReferenceAdmin


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


class ProductModelSpecificationInline(admin.TabularInline):
    model = ProductModelSpecification
    extra = 0
    fields = ("definition", "value")
    autocomplete_fields = ("definition",)


@admin.register(EquipmentCategory)
class EquipmentCategoryAdmin(ProtectedReferenceAdmin):
    """View-only: categories are provisioned defaults (``core/labs/features/equipment/defaults.py``).

    Code depends on their keys and capability flags, so the admin cannot add, change or delete them;
    change the declaration and run ``provision_reference_data`` instead. The kinds inline is shown
    read-only as an overview; kinds are edited on the Equipment kinds page.
    """

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    list_display = ("name", "kind_count", "bookable", "placeable_on_bench", "calibratable", "monitored", "active")
    list_filter = ("active", "bookable", "monitored")
    search_fields = ("name",)
    inlines = [EquipmentKindInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_kinds=Count("kinds"))

    @admin.display(description="Kinds", ordering="_kinds")
    def kind_count(self, obj):
        return obj._kinds


@admin.register(EquipmentKind)
class EquipmentKindAdmin(LabMangoModelAdmin):
    list_display = ("name", "category", "type_count", "active")
    list_select_related = ("category",)
    list_filter = ("category", "active")
    search_fields = ("name", "category__name")
    inlines = [EquipmentTypeInline]
    label_select_related = ("category",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_types=Count("types"))

    @admin.display(description="Types", ordering="_types")
    def type_count(self, obj):
        return obj._types


@admin.register(EquipmentType)
class EquipmentTypeAdmin(LabMangoModelAdmin):
    list_display = ("name", "kind_name", "category_name", "active")
    list_select_related = ("kind__category",)
    list_filter = ("kind__category", "active")
    search_fields = ("name", "kind__name", "kind__category__name")
    autocomplete_fields = ("kind",)
    label_select_related = ("kind__category",)

    @admin.display(description="Kind", ordering="kind__name")
    def kind_name(self, obj):
        return obj.kind.name

    @admin.display(description="Category", ordering="kind__category__name")
    def category_name(self, obj):
        return obj.kind.category.name


@admin.register(EquipmentManufacturer)
class EquipmentManufacturerAdmin(LabMangoModelAdmin):
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
class EquipmentProductModelAdmin(LabMangoModelAdmin):
    list_display = ("name", "manufacturer", "type_name", "kind_name", "category_name", "active")
    list_select_related = ("manufacturer", "equipment_type__kind__category")
    list_filter = ("equipment_type__kind__category", "manufacturer", "active")
    search_fields = ("name", "manufacturer__name", "equipment_type__name")
    autocomplete_fields = ("manufacturer", "equipment_type")
    inlines = [ProductModelSpecificationInline]
    label_select_related = ("manufacturer",)

    @admin.display(description="Type", ordering="equipment_type__name")
    def type_name(self, obj):
        return obj.equipment_type.name

    @admin.display(description="Kind", ordering="equipment_type__kind__name")
    def kind_name(self, obj):
        return obj.equipment_type.kind.name

    @admin.display(description="Category", ordering="equipment_type__kind__category__name")
    def category_name(self, obj):
        return obj.equipment_type.kind.category.name


@admin.register(SpecificationDefinition)
class SpecificationDefinitionAdmin(LabMangoModelAdmin):
    list_display = ("name", "category", "unit", "value_type", "active")
    list_select_related = ("category",)
    list_filter = ("category", "value_type", "active")
    search_fields = ("name", "unit", "category__name")
    ordering = ("category__name", "name")


admin.site.register(
    (EquipmentInterface, Material, NetworkingProtocol, SampleCustomer, SampleCharacteristic),
    NamedLookupAdmin,
)


@admin.register(DisplaySize)
class DisplaySizeAdmin(LabMangoModelAdmin):
    list_display = ("size", "diagonal_in")
    search_fields = ("size",)
    ordering = ("diagonal_in",)


@admin.register(DisplayResolution)
class DisplayResolutionAdmin(LabMangoModelAdmin):
    list_display = ("resolution", "width_px", "height_px")
    search_fields = ("resolution",)
    ordering = ("width_px", "height_px")


@admin.register(Equipment)
class EquipmentAdmin(LabMangoModelAdmin):
    list_display = (
        "name",
        "sku",
        "kind",
        "manufacturer",
        "product_model",
        "serial_number",
        "lifecycle_state",
        "department",
    )
    list_select_related = (
        "kind__category",
        "manufacturer",
        "product_model__manufacturer",
        "department",
    )
    list_filter = ("lifecycle_state", "kind__category", "calibration_required")
    search_fields = ("name", "sku", "serial_number", "mac_address")
    autocomplete_fields = (
        "owner",
        "department",
        "group",
        "kind",
        "type",
        "manufacturer",
        "product_model",
        "material",
        "size",
        "resolution",
        "protocol",
        "customer",
    )
    filter_horizontal = ("interfaces", "characteristics")
    readonly_fields = ("uid",)


@admin.register(ComputingProfile)
class ComputingProfileAdmin(LabMangoModelAdmin):
    list_display = ("equipment", "hostname", "ip_address", "os_name", "technical_user")
    list_select_related = ("equipment", "technical_user")
    search_fields = ("hostname", "ip_address", "os_name", "equipment__name", "equipment__sku")
    autocomplete_fields = ("equipment", "technical_user")
