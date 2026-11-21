"""Labs roles: who a person is in the lab. Design: ``docs/proposals/role-based-access-redesign.md``.

A role is assigned to people through their URS group (``URSGroup.labs_role``, edited in Django admin).
Roles say nothing about endpoints or features: what a role may do is the set of permissions it grants
(``core.users.permissions.ROLE_PERMISSIONS``). Code outside ``core.users`` never checks a role.

Stored values are persisted and must not change; labels are the names people see.

* Lab Administrator (``admin``): owns the lab system: user directory, equipment reference data, agent
  configuration, imports, device profile approval.
* Lab Coordinator (``coord``): runs daily lab operations: resources, downtime, everyone's bookings and
  their approval, monitoring, procurement, expenses and finance reports, support requests.
* Lab Member (``member``): uses the lab: dashboard, leaderboard and own bench bookings.

*Lab operator* is the umbrella term for a person whose role grants lab operations authority
(``LabsPermission.LAB_OPERATIONS_MANAGE``): today Lab Coordinators and Lab Administrators.
"""

from django.db import models

from core.common.api.permissions import RoleHierarchy


class LabsRole(models.TextChoices):
    """Labs roles. Values are persisted in ``URSGroup.labs_role``."""

    ADMIN = "admin", "Lab Administrator"
    COORDINATOR = "coord", "Lab Coordinator"
    MEMBER = "member", "Lab Member"


# Higher roles imply lower ones: a Lab Administrator also holds everything a Lab Coordinator holds.
LABS_ROLE_HIERARCHY = RoleHierarchy(
    grants={
        LabsRole.ADMIN: (LabsRole.COORDINATOR, LabsRole.MEMBER),
        LabsRole.COORDINATOR: (LabsRole.MEMBER,),
        LabsRole.MEMBER: (),
    }
)


__all__ = ["LABS_ROLE_HIERARCHY", "LabsRole"]
