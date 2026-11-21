"""The Labs permission registry: one source for the access matrix, kept consistent and documented."""

import re
from pathlib import Path

from django.conf import settings

from core.users.permissions import (
    ACCESS_MATRIX_PATH,
    ROLE_PERMISSIONS,
    LabsPermission,
    permissions_for_roles,
    render_access_matrix,
    roles_granting,
)
from core.users.roles import LABS_ROLE_HIERARCHY, LabsRole


def test_every_permission_is_granted_by_some_role():
    granted = set().union(*ROLE_PERMISSIONS.values())
    assert set(LabsPermission) == granted, "Grant or remove: " + ", ".join(sorted(set(LabsPermission) - granted))


def test_every_role_is_mapped():
    assert set(ROLE_PERMISSIONS) == set(LabsRole)


def test_roles_do_not_repeat_permissions_they_already_imply():
    for role, added in ROLE_PERMISSIONS.items():
        implied = LABS_ROLE_HIERARCHY.expand([role]) - {role}
        repeated = added & permissions_for_roles(implied)
        assert not repeated, f"{role} repeats {sorted(repeated)}, already granted by a lower role"


def test_permission_codes_are_area_dot_action():
    for permission in LabsPermission:
        assert re.fullmatch(r"[a-z_]+\.[a-z_]+", permission.value), permission.value
        assert permission.label and permission.label[0].isupper(), permission.value


def test_higher_roles_hold_everything_lower_roles_hold():
    member = permissions_for_roles([LabsRole.MEMBER])
    coordinator = permissions_for_roles([LabsRole.COORDINATOR])
    admin = permissions_for_roles([LabsRole.ADMIN])
    assert member < coordinator < admin


def test_unknown_roles_grant_nothing():
    assert permissions_for_roles(["root", ""]) == frozenset()


def test_roles_granting_includes_roles_that_imply_the_grant():
    assert roles_granting(LabsPermission.DASHBOARD_READ) == set(LabsRole)
    assert roles_granting(LabsPermission.LAB_OPERATIONS_MANAGE) == {LabsRole.COORDINATOR, LabsRole.ADMIN}
    assert roles_granting(LabsPermission.DIRECTORY_READ) == {LabsRole.ADMIN}


def test_access_matrix_document_is_current():
    path = Path(settings.BASE_DIR) / ACCESS_MATRIX_PATH
    assert path.read_text(encoding="utf-8") == render_access_matrix(), "Run: uv run python manage.py access_matrix"
