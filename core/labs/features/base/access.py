"""Labs access policy: who may call Labs endpoints (owner decision 2026-11-11).

* Default for every Labs endpoint: lab coordinators and admins read and write (``LABS_STAFF_ACCESS``).
* Plain Labs users (role ``user``) read only the dashboard (overview, summary and bench detail, including
  its equipment mapping) and the leaderboard (``LABS_MEMBER_READ_ACCESS``), and manage their own bench
  bookings (``LABS_MEMBER_ACCESS``; ownership is enforced per object). They have no access to the
  benches, equipment, licenses, locations or other Labs endpoints.
* Users without a Labs role get nothing. API keys keep their existing access until the authentication
  proposal (M11) turns them off in production.

Every Labs view inherits one of these from the Labs base views, or sets it explicitly.
``tests/architecture/test_labs_access_policy.py`` walks every ``/api/labs/`` route and fails when a route
is not covered.
"""

from rest_framework_api_key.permissions import HasAPIKey

from core.users.public import IsLabCoordinatorReadWrite, IsLabMember, IsLabMemberReadOnly

LABS_STAFF_ACCESS = [HasAPIKey | IsLabCoordinatorReadWrite]
LABS_MEMBER_ACCESS = [HasAPIKey | IsLabMember]
LABS_MEMBER_READ_ACCESS = [HasAPIKey | IsLabMemberReadOnly]

__all__ = ["LABS_MEMBER_ACCESS", "LABS_MEMBER_READ_ACCESS", "LABS_STAFF_ACCESS"]
