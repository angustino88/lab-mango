"""Labs permissions: what can be done, and which role grants it. The single source of the access matrix.

Design: ``docs/proposals/role-based-access-redesign.md``. Features check a permission (``has_permission``,
``LabsAccessPolicy``), never a role, so changing who may do something is one line in ``ROLE_PERMISSIONS``.

Rules for this registry:

* One permission per business capability (``area.action``), not per endpoint or model. Add one only when
  a different set of people needs an action; otherwise reuse the permission of the area.
* Values are API-visible (``GET /api/users/me``) and stable: rename by adding the new value and removing
  the old one in a reviewed change, never by editing a value in place.
* The label is the description shown to people and in the generated access matrix
  (``docs/architecture/access-matrix.md``, kept in sync by ``core/users/tests/test_permissions.py``).
* Each role lists only the permissions it *adds*; ``LABS_ROLE_HIERARCHY`` adds the lower roles' grants.
"""

from collections.abc import Iterable

from django.db import models

from core.users.roles import LABS_ROLE_HIERARCHY, LabsRole


class LabsPermission(models.TextChoices):
    """Every Labs permission. The label describes what it allows."""

    # Lab Member
    DASHBOARD_READ = "dashboard.read", "Read the dashboard: overview, summary and bench detail with equipment mapping"
    LEADERBOARD_READ = (
        "leaderboard.read",
        "Read the leaderboard, bench and user profiles and usage, and one's own assessment",
    )
    BENCH_BOOKING_MANAGE_OWN = (
        "bench_booking.manage_own",
        "Create, change and cancel one's own bench bookings; read the bench picker and lab projects for booking",
    )
    ORGANIZATION_READ = "organization.read", "Read the organization lookups (departments, groups) other screens use"

    # Lab Coordinator (lab operator)
    LAB_OPERATIONS_MANAGE = (
        "lab_operations.manage",
        "Read and manage lab resources and operations: rooms, stations, benches, equipment, licenses, downtime, "
        "monitoring, telemetry, resource mappings, resource audit, lab sessions and analytics",
    )
    FINANCE_MANAGE = "finance.manage", "Read and manage procurement, expenses and finance reports"
    BENCH_BOOKING_MANAGE_ANY = "bench_booking.manage_any", "Read and change everyone's bench bookings"
    BENCH_BOOKING_APPROVE = "bench_booking.approve", "Approve or reject bench bookings that need approval"
    BENCH_BOOKING_BOOK_DURING_DOWNTIME = (
        "bench_booking.book_during_downtime",
        "Book benches during downtime windows that stay open to lab operators",
    )
    ASSESSMENT_READ_ANY = "assessment.read_any", "Read the KPI assessment of any user or bench"
    REFERENCE_DATA_IMPORT = (
        "reference_data.import",
        "Add lab reference data: lab projects and bench, location and license catalogs",
    )
    AGENT_MANAGE = "agent.manage", "Read, register, grant, revoke and decommission agents"
    SUPPORT_HANDLE = "support.handle", "Handle support tickets as an agent"

    # Lab Administrator
    EQUIPMENT_REFERENCE_MANAGE = (
        "equipment_reference.manage",
        "Add equipment reference data: catalogs and the lookups equipment points at (OD12)",
    )
    LICENSE_CHECK_MANAGE = "license_check.manage", "Change which license checks agents run"
    WORKBOOK_IMPORT = "workbook.import", "Import the lab data workbook"
    TELEMETRY_PROFILE_APPROVE = "telemetry_profile.approve", "Approve telemetry device profiles after their bench test"
    SUPPORT_ADMINISTER = "support.administer", "Administer the support desk"
    DIRECTORY_READ = "directory.read", "Read user groups and their members"


_P = LabsPermission

ROLE_PERMISSIONS: dict[str, frozenset[LabsPermission]] = {
    LabsRole.MEMBER: frozenset(
        {
            _P.DASHBOARD_READ,
            _P.LEADERBOARD_READ,
            _P.BENCH_BOOKING_MANAGE_OWN,
            _P.ORGANIZATION_READ,
        }
    ),
    LabsRole.COORDINATOR: frozenset(
        {
            _P.LAB_OPERATIONS_MANAGE,
            _P.FINANCE_MANAGE,
            _P.BENCH_BOOKING_MANAGE_ANY,
            _P.BENCH_BOOKING_APPROVE,
            _P.BENCH_BOOKING_BOOK_DURING_DOWNTIME,
            _P.ASSESSMENT_READ_ANY,
            _P.REFERENCE_DATA_IMPORT,
            _P.AGENT_MANAGE,
            _P.SUPPORT_HANDLE,
        }
    ),
    LabsRole.ADMIN: frozenset(
        {
            _P.EQUIPMENT_REFERENCE_MANAGE,
            _P.LICENSE_CHECK_MANAGE,
            _P.WORKBOOK_IMPORT,
            _P.TELEMETRY_PROFILE_APPROVE,
            _P.SUPPORT_ADMINISTER,
            _P.DIRECTORY_READ,
        }
    ),
}

ALL_PERMISSIONS: frozenset[str] = frozenset(LabsPermission.values)


def permissions_for_roles(roles: Iterable[str]) -> frozenset[str]:
    """Every permission granted by ``roles`` and the roles they imply. Unknown roles grant nothing."""
    granted: set[str] = set()
    for role in LABS_ROLE_HIERARCHY.expand(roles):
        granted.update(ROLE_PERMISSIONS.get(role, ()))
    return frozenset(granted)


def roles_granting(permission: str) -> frozenset[str]:
    """Every role whose effective permissions include ``permission`` (implied grants included)."""
    return frozenset(role for role in LABS_ROLE_HIERARCHY.roles if permission in permissions_for_roles([role]))


ACCESS_MATRIX_PATH = "docs/architecture/access-matrix.md"


def render_access_matrix() -> str:
    """The access matrix document generated from this registry (``manage.py access_matrix``)."""
    roles = (LabsRole.MEMBER, LabsRole.COORDINATOR, LabsRole.ADMIN)
    lines = [
        "# Labs access matrix",
        "",
        "<!-- Generated by `uv run python manage.py access_matrix` from `core/users/permissions.py`. Do not edit. -->",
        "",
        "Who may do what in Lab Mango. Roles are assigned through URS groups; each role holds the permissions",
        "marked below (higher roles hold everything lower roles hold). Superusers hold every permission.",
        "*Lab operators* are the roles holding `lab_operations.manage`. Design:",
        "[role-based access redesign](../proposals/role-based-access-redesign.md).",
        "",
        "| Permission | Allows | " + " | ".join(f"{role.label} (`{role.value}`)" for role in roles) + " |",
        "|---|---|" + "---|" * len(roles),
    ]
    for permission in LabsPermission:
        marks = " | ".join("yes" if permission in permissions_for_roles([role]) else "" for role in roles)
        lines.append(f"| `{permission.value}` | {permission.label} | {marks} |")
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "ACCESS_MATRIX_PATH",
    "ALL_PERMISSIONS",
    "ROLE_PERMISSIONS",
    "LabsPermission",
    "permissions_for_roles",
    "render_access_matrix",
    "roles_granting",
]
