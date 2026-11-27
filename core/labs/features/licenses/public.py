"""Supported commands and read queries for license workflows."""

from .application import (
    AssignLicenseInput,
    ChangeLicenseStatusInput,
    CreateLicenseInput,
    DeleteLicenseInput,
    UnassignLicenseInput,
    UpdateLicenseInput,
    assign_license,
    change_license_status,
    create_license,
    delete_license,
    license_images,
    unassign_license,
    update_license,
)
from .application.expiry_alerts import ExpiryAlertResult, send_license_expiry_alerts
from .exceptions import InvalidLicenseStatus, LicenseAlreadyAssigned, LicenseConflict
from .queries import (
    active_license_assignment_mapping_rows,
    get_active_license,
    get_license,
    get_license_for_mapping,
    license_mapping_rows,
    list_license_status_history,
    list_licenses,
)
from .queries.summaries import get_license_status_summary, list_license_category_summary
from .queries.lookup import lookup_licenses

__all__ = (
    "lookup_licenses",
    "ExpiryAlertResult",
    "send_license_expiry_alerts",
    "get_license_status_summary",
    "list_license_category_summary",
    "AssignLicenseInput",
    "ChangeLicenseStatusInput",
    "CreateLicenseInput",
    "DeleteLicenseInput",
    "InvalidLicenseStatus",
    "LicenseAlreadyAssigned",
    "LicenseConflict",
    "UnassignLicenseInput",
    "UpdateLicenseInput",
    "assign_license",
    "active_license_assignment_mapping_rows",
    "change_license_status",
    "create_license",
    "delete_license",
    "get_license",
    "get_license_for_mapping",
    "license_images",
    "license_mapping_rows",
    "get_active_license",
    "list_license_status_history",
    "list_licenses",
    "unassign_license",
    "update_license",
)
