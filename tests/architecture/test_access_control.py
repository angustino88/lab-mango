"""Access control guardrails (design: docs/proposals/role-based-access-redesign.md).

Production code outside ``core.users`` checks permissions, never roles: it imports access control only from
``core.users.public`` and never ``core.users.roles``, ``core.users.access`` or ``core.users.permissions``.
The removed role API (``has_labs_role``, ``IsLab*`` classes, ``LABS_*_ACCESS``) must not come back. Route
coverage is checked per area in ``core/labs/tests/test_access_policy.py``.
"""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = PROJECT_ROOT / "core"
RBAC_INTERNALS = ("core.users.roles", "core.users.access", "core.users.permissions")
REMOVED_NAMES = {
    "LabsRole",
    "has_labs_role",
    "effective_labs_roles",
    "users_holding_labs_role",
    "RolePermission",
    "LABS_STAFF_ACCESS",
    "LABS_MEMBER_ACCESS",
    "LABS_MEMBER_READ_ACCESS",
}


def _production_files():
    for path in CORE_ROOT.rglob("*.py"):
        parts = path.relative_to(CORE_ROOT).parts
        if {"tests", "migrations", "__pycache__"} & set(parts[:-1]):
            continue
        yield path


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module, [alias.name for alias in node.names]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, []


def test_only_core_users_resolves_roles():
    violations = []
    for path in _production_files():
        relative = path.relative_to(PROJECT_ROOT)
        if relative.parts[:2] == ("core", "users"):
            continue
        for module, names in _imports(path):
            if any(module == internal or module.startswith(f"{internal}.") for internal in RBAC_INTERNALS):
                violations.append(f"{relative}: imports {module} (use core.users.public)")
            if module.startswith("core.") and REMOVED_NAMES & set(names):
                violations.append(f"{relative}: imports {sorted(REMOVED_NAMES & set(names))} from {module}")
    assert not violations, "Role checks outside core.users:\n" + "\n".join(violations)


def test_removed_role_api_is_gone_everywhere():
    violations = []
    for path in _production_files():
        source = path.read_text(encoding="utf-8-sig")
        for name in (
            "has_labs_role",
            "users_holding_labs_role",
            "LABS_STAFF_ACCESS",
            "IsLabCoordinator",
            "IsLabMember",
            "IsLabAdmin",
        ):
            if name in source:
                violations.append(f"{path.relative_to(PROJECT_ROOT)}: {name}")
    assert not violations, "Legacy role API still referenced:\n" + "\n".join(violations)
