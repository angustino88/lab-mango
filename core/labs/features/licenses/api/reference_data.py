"""Explicit license lookup import declarations."""

from core.common.api.reference_views import reference_urlpatterns
from core.labs.features.base.access import LABS_STAFF_ACCESS
from core.labs.models.resource.license.license import (
    LicenseCategory,
    LicenseProduct,
    LicenseRestriction,
    LicenseType,
    LicenseVendor,
)
from core.reference_data.contracts import ReferenceResource

from ..application.reference_data import create_catalog_reference
from ..queries.reference_data import get_catalog_reference, list_catalog_references

RESOURCES = (
    ("vendors", LicenseVendor, ("name",)),
    ("products", LicenseProduct, ("name", "vendor")),
    ("types", LicenseType, ("name",)),
    ("categories", LicenseCategory, ("name",)),
    ("restrictions", LicenseRestriction, ("name",)),
)
urlpatterns = []
for segment, model, fields in RESOURCES:
    urlpatterns += reference_urlpatterns(
        resource=ReferenceResource(f"license-reference-{segment}", model, fields, ("name",)),
        prefix=f"licenses/reference-data/{segment}",
        tag="Licenses",
        module=__name__,
        permission_classes=LABS_STAFF_ACCESS,
        create=create_catalog_reference,
        listing=list_catalog_references,
        retrieve=get_catalog_reference,
    )
