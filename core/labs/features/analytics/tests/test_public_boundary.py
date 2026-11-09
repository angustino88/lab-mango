"""Static tests for analytics feature layer boundaries and exports."""

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


def test_public_surface_exports_application_queries_and_exception():
    exports = _exports(FEATURE_ROOT / "public.py")
    assert "RecordStorageQuotaInput" in exports
    assert "RecordFacilityVisitInput" in exports
    assert "record_storage_quota_measurement" in exports
    assert "record_facility_visit" in exports
    assert "snapshot_daily_booking_volume" in exports
    assert "snapshot_daily_active_benches" in exports
    assert "get_booking_volume_metrics" in exports
    assert "list_storage_quota_measurements" in exports


def test_api_adapters_use_public_and_have_no_direct_model_workflows():
    views = FEATURE_ROOT / "api" / "views.py"
    imports = _imports(views)
    source = views.read_text(encoding="utf-8-sig")
    assert "core.labs.models" not in imports
    assert "BookingCountAPIView" in source
    assert "StorageQuotaAPIView" in source
