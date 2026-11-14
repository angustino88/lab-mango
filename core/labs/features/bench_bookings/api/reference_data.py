"""Project import API alongside the compatible existing project read routes."""

from core.common.api.reference_views import reference_urlpatterns
from core.labs.features.base.access import LABS_MEMBER_ACCESS, can_import_lab_reference_data
from core.labs.models import LabProject
from core.reference_data.contracts import ReferenceResource

from ..application.reference_data import create_catalog_reference
from ..queries.reference_data import get_catalog_reference, list_catalog_references

urlpatterns = reference_urlpatterns(
    resource=ReferenceResource(
        "booking-reference-projects",
        LabProject,
        ("project_name", "code", "starts_on", "ends_on", "active"),
        ("project_name",),
        "project_name",
        wire_names=(("starts_on", "start_date"), ("ends_on", "end_date")),
    ),
    prefix="bench-bookings/reference-data/projects",
    tag="Bench Bookings",
    module=__name__,
    permission_classes=LABS_MEMBER_ACCESS,
    can_write=can_import_lab_reference_data,
    create=create_catalog_reference,
    listing=list_catalog_references,
    retrieve=get_catalog_reference,
)
