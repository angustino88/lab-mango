"""Static tests for the licenses feature's supported import surface."""

import ast
from pathlib import Path

FEATURE_ROOT = Path(__file__).resolve().parents[1]


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _exports(path: Path) -> list[str]:
    for node in _module(path).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path} must declare __all__")


def _absolute_imports(path: Path) -> set[str]:
    return {
        node.module
        for node in ast.walk(_module(path))
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None
    }


def test_exceptions_export_stable_errors_without_layer_imports():
    exceptions = FEATURE_ROOT / "exceptions.py"
    assert set(_exports(exceptions)) == {"InvalidLicenseStatus", "LicenseAlreadyAssigned"}
    assert not any(".application" in name or ".queries" in name for name in _absolute_imports(exceptions))


def test_public_module_exports_license_commands_and_queries():
    public = FEATURE_ROOT / "public.py"
    assert set(_exports(public)) == {
        "AssignLicenseInput",
        "ChangeLicenseStatusInput",
        "CreateLicenseAgreementInput",
        "InvalidLicenseStatus",
        "LicenseAlreadyAssigned",
        "UnassignLicenseInput",
        "active_license_assignment_mapping_rows",
        "assign_license",
        "change_license_status",
        "create_license_agreement",
        "get_active_license",
        "get_license",
        "get_license_status_summary",
        "list_license_category_summary",
        "get_license_for_mapping",
        "license_mapping_rows",
        "list_license_agreements",
        "list_license_status_history",
        "list_licenses",
        "unassign_license",
    }
    source = (FEATURE_ROOT / "public.py").read_text(encoding="utf-8-sig")
    assert ".application import" in source
    assert ".queries import" in source


def test_api_uses_public_workflows_and_contract_errors():
    api = FEATURE_ROOT / "api" / "views.py"
    source = api.read_text(encoding="utf-8-sig")
    imports = _absolute_imports(api)
    assert "core.labs.features.licenses" in imports
    assert "core.labs.features.licenses.public" in imports
    assert not any(".application" in name or ".queries" in name for name in imports)
    assert "public." in source


def test_application_commands_use_frozen_inputs_and_keyword_only_actor():
    for filename in ("assignments.py", "status.py", "agreements.py"):
        tree = _module(FEATURE_ROOT / "application" / filename)
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        assert classes
        assert all(
            any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name)
                and decorator.func.id == "dataclass"
                and any(
                    keyword.arg == "frozen" and isinstance(keyword.value, ast.Constant) and keyword.value.value
                    for keyword in decorator.keywords
                )
                for decorator in cls.decorator_list
            )
            for cls in classes
        )


def test_layer_package_exports_are_explicit_and_legacy_modules_absent():
    application = FEATURE_ROOT / "application" / "__init__.py"
    queries = FEATURE_ROOT / "queries" / "__init__.py"
    assert set(_exports(application)) == {
        "AssignLicenseInput", "ChangeLicenseStatusInput", "CreateLicenseAgreementInput",
        "UnassignLicenseInput", "assign_license", "change_license_status",
        "create_license_agreement", "unassign_license",
    }
    assert set(_exports(queries)) == {
        "active_license_assignment_mapping_rows", "get_active_license", "get_license",
        "get_license_for_mapping", "license_mapping_rows", "list_license_agreements",
        "list_license_status_history", "list_licenses",
    }
    assert not (FEATURE_ROOT / "services").exists()
    assert not (FEATURE_ROOT / "selectors.py").exists()
    assert set(_exports(FEATURE_ROOT / "application" / "assignments.py")) == {
        "AssignLicenseInput", "UnassignLicenseInput", "assign_license", "unassign_license",
    }
    assert set(_exports(FEATURE_ROOT / "application" / "status.py")) == {
        "ChangeLicenseStatusInput", "change_license_status",
    }
    assert set(_exports(FEATURE_ROOT / "application" / "agreements.py")) == {
        "CreateLicenseAgreementInput", "create_license_agreement",
    }
    assert set(_exports(FEATURE_ROOT / "queries" / "selectors.py")) == {
        "active_license_assignment_mapping_rows", "get_active_license", "get_license",
        "get_license_for_mapping", "license_mapping_rows", "list_license_agreements",
        "list_license_status_history", "list_licenses",
    }


def test_license_api_uses_public_feature_surface_without_direct_model_reads():
    api = FEATURE_ROOT / "api" / "views.py"
    imports = _absolute_imports(api)
    source = api.read_text(encoding="utf-8-sig")
    assert "core.labs.features.licenses" in imports
    assert "public." in source
    assert "core.labs.models" not in imports
    # Domain errors propagate to the global mapper; views do not catch them.
    assert "except " not in source
