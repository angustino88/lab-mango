"""Static tests for dashboard feature layer boundaries and exports."""

import ast
from pathlib import Path

FEATURE_ROOT = Path(__file__).resolve().parents[1]


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _exports(path: Path) -> set[str]:
    for node in _module(path).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            return set(ast.literal_eval(node.value))
    raise AssertionError(f"{path} must declare __all__")


def _imports(path: Path) -> set[str]:
    return {
        node.module
        for node in ast.walk(_module(path))
        if isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0
    }


def test_public_surface_exports_queries_dtos_and_exceptions():
    exports = _exports(FEATURE_ROOT / "public.py")
    expected = {
        "DashboardBenchDetailDTO",
        "DashboardBenchGroupDTO",
        "DashboardBenchItemDTO",
        "DashboardBenchTypeDTO",
        "DashboardBookingDTO",
        "DashboardComputingDTO",
        "DashboardEquipmentItemDTO",
        "DashboardEquipmentCategoryDTO",
        "DashboardEquipmentReferenceDTO",
        "DashboardError",
        "DashboardFilterError",
        "DashboardLocationDTO",
        "DashboardResourceNotFound",
        "DashboardSummaryDTO",
        "DashboardUserDTO",
        "get_dashboard_bench_detail",
        "get_dashboard_summary",
        "list_dashboard_benches",
    }
    assert expected == exports


def test_exceptions_export_only_domain_error_types():
    exceptions_path = FEATURE_ROOT / "exceptions.py"
    exports = _exports(exceptions_path)
    assert exports == {
        "DashboardError",
        "DashboardFilterError",
        "DashboardResourceNotFound",
    }
    imports = _imports(exceptions_path)
    assert not any("application" in module or "queries" in module or "models" in module for module in imports)


def test_api_views_have_no_direct_model_imports():
    views_path = FEATURE_ROOT / "api" / "views.py"
    imports = _imports(views_path)
    source = views_path.read_text(encoding="utf-8-sig")
    assert "core.labs.models" not in imports
    assert "DashboardOverviewAPIView" in source
    assert "DashboardSummaryAPIView" in source
    assert "DashboardBenchDetailAPIView" in source


def test_contracts_contain_only_neutral_types():
    contracts_path = FEATURE_ROOT / "contracts.py"
    imports = _imports(contracts_path)
    assert not any("django" in module or "rest_framework" in module for module in imports)
