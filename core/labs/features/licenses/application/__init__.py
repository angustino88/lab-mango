"""License write use cases."""

from .agreements import CreateLicenseAgreementInput, create_license_agreement
from .assignments import (
    AssignLicenseInput,
    UnassignLicenseInput,
    assign_license,
    unassign_license,
)
from .status import ChangeLicenseStatusInput, change_license_status

__all__ = [
    "AssignLicenseInput",
    "ChangeLicenseStatusInput",
    "CreateLicenseAgreementInput",
    "UnassignLicenseInput",
    "assign_license",
    "change_license_status",
    "create_license_agreement",
    "unassign_license",
]
