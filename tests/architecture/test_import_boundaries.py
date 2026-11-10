"""Architecture guardrails for shared and technical packages."""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = PROJECT_ROOT / "core"

BUSINESS_PACKAGES = (
    "core.labs",
    "core.users",
    "core.websocket",
    "core.support_desk",
    "core.agents",
    "core.routing",
)


def _production_python_files(package_path: Path):
    excluded_directories = {"__pycache__", "migrations", "tests"}
    for path in package_path.rglob("*.py"):
        if not excluded_directories.intersection(path.relative_to(package_path).parts[:-1]):
            yield path


def _imported_modules(source_path: Path):
    source = source_path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(source_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module


def _is_within_package(module_name: str, package_name: str) -> bool:
    return module_name == package_name or module_name.startswith(f"{package_name}.")


def _boundary_violations(package_name: str, forbidden_packages: tuple[str, ...]):
    violations = []
    package_path = CORE_ROOT / package_name.removeprefix("core.")
    for source_path in _production_python_files(package_path):
        for imported_module in _imported_modules(source_path):
            if any(_is_within_package(imported_module, name) for name in forbidden_packages):
                relative_path = source_path.relative_to(PROJECT_ROOT)
                violations.append(f"{relative_path}: imports {imported_module}")
    return violations


def test_common_does_not_depend_on_business_apps_or_adapters():
    forbidden = (*BUSINESS_PACKAGES, "core.infrastructure", "config")
    violations = _boundary_violations("core.common", forbidden)

    assert not violations, "Common package boundary violations:\n" + "\n".join(violations)


def test_infrastructure_does_not_depend_on_business_apps_or_runtime_config():
    violations = _boundary_violations("core.infrastructure", (*BUSINESS_PACKAGES, "config"))

    assert not violations, "Infrastructure package boundary violations:\n" + "\n".join(violations)
