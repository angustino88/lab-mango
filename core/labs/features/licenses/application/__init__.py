"""License write use cases."""

from core.labs.features.base.resource_image_commands import ResourceImageCommands
from core.labs.models import License

from .agreements import CreateLicenseAgreementInput, create_license_agreement
from .assignments import (
    AssignLicenseInput,
    UnassignLicenseInput,
    assign_license,
    unassign_license,
)
from .inventory import (
    CreateLicenseInput,
    DeleteLicenseInput,
    UpdateLicenseInput,
    create_license,
    delete_license,
    update_license,
)
from .status import ChangeLicenseStatusInput, change_license_status

# Image use cases (replace/remove) for this resource; see core/labs/features/base/resource_image_commands.py.
license_images = ResourceImageCommands(License)


__all__ = [
    "license_images",
    "AssignLicenseInput",
    "ChangeLicenseStatusInput",
    "CreateLicenseAgreementInput",
    "CreateLicenseInput",
    "DeleteLicenseInput",
    "UnassignLicenseInput",
    "UpdateLicenseInput",
    "assign_license",
    "change_license_status",
    "create_license",
    "create_license_agreement",
    "delete_license",
    "unassign_license",
    "update_license",
]
