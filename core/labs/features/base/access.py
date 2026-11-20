"""Labs endpoint access policies: the permission each Labs area requires (design: role-based-access-redesign.md).

Who holds each permission is decided only in ``core.users.permissions.ROLE_PERMISSIONS``; this module only
says which permission an endpoint needs. Every Labs view inherits ``LAB_OPERATIONS_ACCESS`` from the Labs
base views or sets one of the policies below. ``core/labs/tests/test_access_policy.py`` walks every
``/api/labs/`` route and fails when a route is not covered.

* ``LAB_OPERATIONS_ACCESS`` (default): lab operators read and write.
* ``DASHBOARD_ACCESS``, ``LEADERBOARD_ACCESS``: every Labs role reads; nobody writes.
* ``BENCH_BOOKING_ACCESS``: every Labs role reads and writes; ownership is enforced per object.
* ``BENCH_BOOKING_DECISION_ACCESS``: approving or rejecting a booking.
* ``FINANCE_ACCESS``: procurement, expenses and finance reports.
* ``ORGANIZATION_ACCESS``: departments and groups lookups every Labs role reads.
* ``WORKBOOK_IMPORT_ACCESS``: the data workbook import (Lab Administrators).

API keys (``HasAPIKeyAccess``) keep access to the policies composed with it while ``API_KEY_ACCESS_ENABLED`` is
on (the default). Users without a Labs role get nothing.
"""

from typing import Any

from core.common.api.permissions import HasAPIKeyAccess, PermissionClasses
from core.users.public import LabsAccessPolicy, LabsPermission, has_permission

_P = LabsPermission

LAB_OPERATIONS_ACCESS: PermissionClasses = [
    HasAPIKeyAccess
    | LabsAccessPolicy.of("LabOperationsAccess", read=_P.LAB_OPERATIONS_MANAGE, write=_P.LAB_OPERATIONS_MANAGE)
]
DASHBOARD_ACCESS: PermissionClasses = [
    HasAPIKeyAccess | LabsAccessPolicy.of("DashboardAccess", read=_P.DASHBOARD_READ, write=None)
]
LEADERBOARD_ACCESS: PermissionClasses = [
    HasAPIKeyAccess | LabsAccessPolicy.of("LeaderboardAccess", read=_P.LEADERBOARD_READ, write=None)
]
BENCH_BOOKING_ACCESS: PermissionClasses = [
    HasAPIKeyAccess
    | LabsAccessPolicy.of("BenchBookingAccess", read=_P.BENCH_BOOKING_MANAGE_OWN, write=_P.BENCH_BOOKING_MANAGE_OWN)
]
BENCH_BOOKING_DECISION_ACCESS: PermissionClasses = [
    LabsAccessPolicy.of(
        "BenchBookingDecisionAccess", read=_P.BENCH_BOOKING_MANAGE_OWN, write=_P.BENCH_BOOKING_APPROVE
    )
]
FINANCE_ACCESS: PermissionClasses = [
    HasAPIKeyAccess | LabsAccessPolicy.of("FinanceAccess", read=_P.FINANCE_MANAGE, write=_P.FINANCE_MANAGE)
]
ORGANIZATION_ACCESS: PermissionClasses = [
    HasAPIKeyAccess
    | LabsAccessPolicy.of("OrganizationAccess", read=_P.ORGANIZATION_READ, write=_P.LAB_OPERATIONS_MANAGE)
]
WORKBOOK_IMPORT_ACCESS: PermissionClasses = [
    LabsAccessPolicy.of("WorkbookImportAccess", read=_P.WORKBOOK_IMPORT, write=_P.WORKBOOK_IMPORT)
]


def can_import_lab_reference_data(actor: Any) -> bool:
    """Write rule for Labs reference data (lab projects; bench, location and license catalogs)."""
    return has_permission(actor, LabsPermission.REFERENCE_DATA_IMPORT)


__all__ = [
    "BENCH_BOOKING_ACCESS",
    "BENCH_BOOKING_DECISION_ACCESS",
    "DASHBOARD_ACCESS",
    "FINANCE_ACCESS",
    "LAB_OPERATIONS_ACCESS",
    "LEADERBOARD_ACCESS",
    "ORGANIZATION_ACCESS",
    "WORKBOOK_IMPORT_ACCESS",
    "can_import_lab_reference_data",
]
