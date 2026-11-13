"""Tests for the feature's supported import surface."""

import ast
from pathlib import Path

from core.labs.features.base.serializers import ResourceWriteSerializerMixin
from core.labs.features.benches.api.serializers import BenchCreateSerializer, BenchUpdateSerializer

FEATURE_ROOT = Path(__file__).resolve().parents[1]


def _absolute_imports(source: str) -> set[str]:
    tree = ast.parse(source)
    return {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None
    }


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _public_names(path: Path) -> list[str]:
    tree = _module(path)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path} must declare __all__")


def test_exceptions_export_only_implementation_free_error_types():
    exceptions_path = FEATURE_ROOT / "exceptions.py"
    policy_path = FEATURE_ROOT / "application" / "policies.py"
    assert _public_names(exceptions_path) == ["BenchConflict"]

    imports = _absolute_imports(exceptions_path.read_text(encoding="utf-8-sig"))
    assert not any(".application" in module or ".queries" in module for module in imports)
    assert "core.labs.features.benches.exceptions" in _absolute_imports(
        policy_path.read_text(encoding="utf-8-sig")
    )


def test_public_exports_supported_commands_and_queries():
    public_path = FEATURE_ROOT / "public.py"
    assert set(_public_names(public_path)) == {
        "BenchConflict",
        "add_favorite",
        "change_bench_lifecycle",
        "bench_mapping_rows",
        "create_bench",
        "delete_bench",
        "get_bench",
        "get_bench_status_summary",
        "get_bench_for_mapping",
        "get_reference",
        "list_benches",
        "list_references",
        "place_bench",
        "reference_data",
        "remove_favorite",
        "retire_reference",
        "save_reference",
        "update_bench",
    }

    imports = _module(public_path).body
    exported_from = {
        ("." * node.level + (node.module or "")): {alias.name for alias in node.names}
        for node in imports
        if isinstance(node, ast.ImportFrom)
    }
    assert exported_from[".application"] == {
        "add_favorite", "change_bench_lifecycle", "create_bench", "delete_bench", "place_bench", "remove_favorite",
        "retire_reference", "save_reference", "update_bench",
    }
    assert exported_from[".queries.selectors"] == {
        "bench_mapping_rows", "get_bench", "get_bench_for_mapping", "get_reference", "list_benches", "list_references", "reference_data",
    }


def test_http_adapter_uses_public_entry_points_not_private_implementations():
    source = Path(FEATURE_ROOT / "api" / "views.py").read_text(encoding="utf-8-sig")
    imports = _absolute_imports(source)

    assert "core.labs.features.benches.application" in imports
    assert "core.labs.features.benches.queries" in imports
    assert "core.labs.features.benches.public" not in imports


def test_application_and_query_package_exports_are_explicit():
    assert set(_public_names(FEATURE_ROOT / "application" / "__init__.py")) == {
        "add_favorite", "change_bench_lifecycle", "create_bench", "delete_bench", "place_bench", "remove_favorite",
        "retire_reference", "save_reference", "update_bench",
    }
    assert set(_public_names(FEATURE_ROOT / "queries" / "__init__.py")) == {
        "bench_mapping_rows", "get_bench", "get_bench_for_mapping", "get_reference", "list_bench_equipment", "list_benches", "list_references", "reference_data",
    }
    assert set(_public_names(FEATURE_ROOT / "application" / "services.py")) == {
        "add_favorite", "change_bench_lifecycle", "create_bench", "delete_bench", "place_bench", "remove_favorite",
        "retire_reference", "save_reference", "update_bench",
    }
    assert set(_public_names(FEATURE_ROOT / "queries" / "selectors.py")) == {
        "bench_mapping_rows", "get_bench", "get_bench_for_mapping", "get_reference", "list_bench_equipment", "list_bench_options", "list_benches", "list_references", "reference_data",
    }
    assert set(_public_names(FEATURE_ROOT / "application" / "policies.py")) == {
        "BenchConflict", "validate_capacity", "validate_slot",
    }


def test_query_layer_owns_reference_data_reads():
    source = (FEATURE_ROOT / "api" / "views.py").read_text(encoding="utf-8-sig")
    assert ".objects." not in source
    assert "core.labs.models" not in _absolute_imports(source)


def test_bench_sku_is_writable_on_create_but_read_only_on_update():
    assert not BenchCreateSerializer().fields["sku"].read_only
    assert not BenchUpdateSerializer().fields["sku"].read_only
    serializer = BenchUpdateSerializer(instance=object(), data={"sku": "NEW"})
    assert not serializer.is_valid()
    assert str(serializer.errors["code"][0]) == "resource_field_immutable"


def test_resource_sku_immutability_is_not_owned_by_locations():
    assert "immutable_update_fields" in ResourceWriteSerializerMixin.__dict__
