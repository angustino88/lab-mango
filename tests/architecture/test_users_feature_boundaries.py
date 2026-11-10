"""Feature-boundary guardrails for the users domain (standard library only).

Rules:
1. Code outside ``core.users.features`` may import a feature module only if it is listed in
   ``LEGACY_EXTERNAL_FEATURE_IMPORTS``. The list records existing violations and may only shrink.
2. Inside ``core.users.features``, a capability (``auth``, ``lifecycle``, ``profile``, ``groups``,
   ``urs_sync``)
   must not import another capability's modules.
"""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
USERS_ROOT = PROJECT_ROOT / "core" / "users"
FEATURES_PACKAGE = "core.users.features"
EXCLUDED_DIRECTORIES = {"__pycache__", "migrations", "tests"}

# Existing/approved violations (path relative to core/users); remove entries as boundaries are repaired.
LEGACY_EXTERNAL_FEATURE_IMPORTS = {
    "admin.py",
    "tasks.py",
    "public.py",
}


def _production_python_files(root: Path):
    for path in root.rglob("*.py"):
        if not EXCLUDED_DIRECTORIES.intersection(path.relative_to(root).parts[:-1]):
            yield path


def _imported_modules(source_path: Path):
    tree = ast.parse(source_path.read_text(encoding="utf-8-sig"), filename=str(source_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module


def _capability(module_name: str) -> str | None:
    """Return the top-level capability for ``core.users.features.<capability>.…`` modules."""
    prefix = f"{FEATURES_PACKAGE}."
    if not module_name.startswith(prefix):
        return None
    return module_name[len(prefix) :].split(".", 1)[0]


def _capability_of_file(source_path: Path) -> str | None:
    relative = source_path.relative_to(USERS_ROOT).parts
    if relative[:1] == ("features",) and len(relative) > 2:
        return relative[1]
    return None


def test_external_code_imports_features_only_through_known_legacy_list():
    violations = []
    for source_path in _production_python_files(USERS_ROOT):
        relative = source_path.relative_to(USERS_ROOT)
        if relative.parts[0] == "features":
            continue
        imports_feature = any(
            module == FEATURES_PACKAGE or module.startswith(f"{FEATURES_PACKAGE}.")
            for module in _imported_modules(source_path)
        )
        if imports_feature and relative.as_posix() not in LEGACY_EXTERNAL_FEATURE_IMPORTS:
            violations.append(f"core/users/{relative.as_posix()} imports a feature module")

    assert not violations, "Users feature boundary violations:\n" + "\n".join(violations)


def test_legacy_external_feature_imports_still_exist_so_the_list_can_shrink():
    stale = [
        name
        for name in LEGACY_EXTERNAL_FEATURE_IMPORTS
        if not any(module.startswith(f"{FEATURES_PACKAGE}.") for module in _imported_modules(USERS_ROOT / name))
    ]

    assert not stale, f"Remove fixed entries from LEGACY_EXTERNAL_FEATURE_IMPORTS: {stale}"


def test_capabilities_do_not_import_each_other():
    violations = []
    features_root = USERS_ROOT / "features"
    for source_path in _production_python_files(features_root):
        owner = _capability_of_file(source_path)
        if owner is None:
            continue
        for module in _imported_modules(source_path):
            target = _capability(module)
            if target is not None and target != owner:
                relative_path = source_path.relative_to(PROJECT_ROOT).as_posix()
                violations.append(f"{relative_path}: {owner} imports {target} ({module})")

    assert not violations, "Cross-capability imports inside core.users.features:\n" + "\n".join(violations)
