"""Labs access policy: who may call Labs endpoints (owner decision 2026-11-11).

* Default for every Labs endpoint: lab coordinators and admins read and write (``LABS_STAFF_ACCESS``).
* Plain Labs users (role ``user``) read only the dashboard (overview, summary and bench detail, including
  its equipment mapping) and the leaderboard (``LABS_MEMBER_READ_ACCESS``), and manage their own bench
  bookings (``LABS_MEMBER_ACCESS``; ownership is enforced per object). They have no access to the
  benches, equipment, licenses, locations or other Labs endpoints.
* Users without a Labs role get nothing. API keys (``HasAPIKeyAccess``) keep access while
  ``API_KEY_ACCESS_ENABLED`` is on (the default); set it off to reject every key-only request.
* Labs reference-data imports (catalogs, projects) are for coordinators and admins
  (``can_import_lab_reference_data``), whatever Django permissions a user holds.

Every Labs view inherits one of these from the Labs base views, or sets it explicitly.
``tests/architecture/test_labs_access_policy.py`` walks every ``/api/labs/`` route and fails when a route
is not covered.
"""

from typing import Any

from core.common.api.permissions import HasAPIKeyAccess
from core.users.public import IsLabCoordinatorReadWrite, IsLabMember, IsLabMemberReadOnly, LabsRole, has_labs_role

LABS_STAFF_ACCESS = [HasAPIKeyAccess | IsLabCoordinatorReadWrite]
LABS_MEMBER_ACCESS = [HasAPIKeyAccess | IsLabMember]
LABS_MEMBER_READ_ACCESS = [HasAPIKeyAccess | IsLabMemberReadOnly]


def can_import_lab_reference_data(actor: Any) -> bool:
    """Labs reference data (catalogs, projects) is imported by lab coordinators and admins only."""
    return has_labs_role(actor, LabsRole.COORDINATOR)


__all__ = ["LABS_MEMBER_ACCESS", "LABS_MEMBER_READ_ACCESS", "LABS_STAFF_ACCESS", "can_import_lab_reference_data"]
