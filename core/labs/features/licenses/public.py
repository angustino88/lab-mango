"""Supported commands and read queries for license workflows."""

from .application import (
    AssignLicenseInput,
    ChangeLicenseStatusInput,
    CreateLicenseAgreementInput,
    UnassignLicenseInput,
    assign_license,
    change_license_status,
    create_license_agreement,
    unassign_license,
)
from .exceptions import InvalidLicenseStatus, LicenseAlreadyAssigned
from .queries import (
    active_license_assignment_mapping_rows,
    get_active_license,
    get_license,
    get_license_for_mapping,
    license_mapping_rows,
    list_license_agreements,
    list_license_status_history,
    list_licenses,
)
from .queries.summaries import get_license_status_summary, list_license_category_summary

__all__ = (
    "get_license_status_summary",
    "list_license_category_summary",
    "AssignLicenseInput",
    "ChangeLicenseStatusInput",
    "CreateLicenseAgreementInput",
    "InvalidLicenseStatus",
    "LicenseAlreadyAssigned",
    "UnassignLicenseInput",
    "assign_license",
    "active_license_assignment_mapping_rows",
    "change_license_status",
    "create_license_agreement",
    "get_license",
    "get_license_for_mapping",
    "license_mapping_rows",
    "get_active_license",
    "list_license_agreements",
    "list_license_status_history",
    "list_licenses",
    "unassign_license",
)
