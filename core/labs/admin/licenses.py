"""License catalog reference data (vendors, products, types, categories, restrictions).

Licenses, agreements, assignments and payments are not registered: they carry money and assignment
rules that live in the license feature's commands.
"""

from django.contrib import admin

from core.common.admin import LabMangoModelAdmin
from core.labs.admin._base import NamedLookupAdmin
from core.labs.models.resource.license.license import (
    LicenseCategory,
    LicenseProduct,
    LicenseRestriction,
    LicenseType,
    LicenseVendor,
)

admin.site.register((LicenseVendor, LicenseType, LicenseCategory, LicenseRestriction), NamedLookupAdmin)


@admin.register(LicenseProduct)
class LicenseProductAdmin(LabMangoModelAdmin):
    list_display = ("name", "vendor", "modified")
    list_select_related = ("vendor",)
    list_filter = ("vendor",)
    search_fields = ("name", "vendor__name")
    autocomplete_fields = ("vendor",)
    ordering = ("vendor__name", "name")
