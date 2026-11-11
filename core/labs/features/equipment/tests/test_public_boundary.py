"""Static tests for the equipment feature's supported import surface."""

import ast
from pathlib import Path

import pytest

FEATURE_ROOT = Path(__file__).resolve().parents[1]

# Categories that own behaviour beyond the shared collection (redesign step 6). Add a category
# here only when it has category-specific logic; every other category has no package at all.
CATEGORIES_WITH_CODE = {"computing"}


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


def test_contracts_are_a_neutral_type_only_boundary():
    contracts = FEATURE_ROOT / "contracts.py"
    assert set(_exports(contracts)) == {"InactiveEquipmentSnapshot", "ActiveEquipmentBenchAssignment"}
    assert "ActiveEquipmentBenchAssignment" in _exports(contracts)
    assert not any("django" in name or "rest_framework" in name for name in _absolute_imports(contracts))


def test_business_errors_are_separate_from_neutral_contracts():
    exceptions = FEATURE_ROOT / "exceptions.py"
    assert _exports(exceptions) == [
        "EquipmentAlreadyAssigned",
        "EquipmentAlreadyPlaced",
        "EquipmentInUse",
        "EquipmentNotAvailable",
        "EquipmentNotOnLoan",
        "EquipmentOnLoan",
        "InvalidEquipmentStatus",
        "LoanIdempotencyKeyRequired",
        "LoanIdempotencyKeyReuse",
        "ReservationConflict",
        "ReservationNotOpen",
        "SkuAlreadyExists",
    ]


def test_public_module_exports_supported_queries_and_commands():
    public = FEATURE_ROOT / "public.py"
    assert set(_exports(public)) == {
        "ActiveEquipmentBenchAssignment",
        "AssignEquipmentInput",
        "ChangeConditionInput",
        "ChangeLifecycleInput",
        "CreateEquipmentInput",
        "DeleteEquipmentInput",
        "UpdateEquipmentInput",
        "UnassignEquipmentInput",
        "EquipmentAlreadyAssigned",
        "EquipmentAlreadyPlaced",
        "EquipmentInUse",
        "EquipmentNotAvailable",
        "EquipmentNotOnLoan",
        "EquipmentOnLoan",
        "InvalidEquipmentStatus",
        "ReservationConflict",
        "ReservationNotOpen",
        "CancelReservationInput",
        "HandOverReservationInput",
        "ReserveEquipmentBatchInput",
        "UpdateReservationInput",
        "cancel_reservation",
        "expire_uncollected_reservations",
        "hand_over_reservation",
        "reserve_equipment_batch",
        "update_reservation",
        "list_reservations",
        "ExtendLoanInput",
        "ExtendLoansInput",
        "LendEquipmentBatchInput",
        "ReturnEquipmentBatchInput",
        "extend_loans",
        "lend_equipment_batch",
        "return_equipment_batch",
        "get_loan_batch",
        "list_loans",
        "HandOverEquipmentInput",
        "ReturnEquipmentInput",
        "extend_loan",
        "hand_over_equipment",
        "return_equipment",
        "get_active_loan",
        "PlaceEquipmentInput",
        "RemovePlacementInput",
        "place_equipment",
        "remove_placement",
        "bench_id_at",
        "get_active_placement",
        "has_active_placements",
        "assign_equipment",
        "change_condition",
        "change_lifecycle",
        "equipment_state_timelines",
        "create_equipment",
        "delete_equipment",
        "update_equipment",
        "list_equipment",
        "unassign_equipment",
        "with_equipment_info",
        "computing_activity_projection",
        "SyncComputingActivityInput",
        "sync_computing_activity",
        "active_bench_assignment_mapping_rows",
        "active_equipment_bench_assignment",
        "lock_active_equipment_bench_assignment",
        "equipment_mapping_rows",
        "get_equipment_for_mapping",
        "inactive_equipment_candidates",
        "get_computing_activity_summary",
        "get_equipment_status_summary",
        "get_equipment_category_status_summary",
    }


def test_api_uses_application_and_query_layers_not_public_facade():
    api = FEATURE_ROOT / "api" / "views.py"
    source = api.read_text(encoding="utf-8-sig")
    imports = _absolute_imports(api)
    assert "core.labs.features.equipment.application" in imports
    assert "core.labs.features.equipment.queries" in imports
    assert "core.labs.features.equipment.public" not in imports
    assert "public." not in source


def test_api_query_implementations_are_not_embedded_in_views():
    views = _module(FEATURE_ROOT / "api" / "views.py")
    query_calls = {
        node.func.id
        for node in ast.walk(views)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"list_equipment", "get_equipment", "equipment_queryset"}
    }
    # Since step 6 the collection views (api/collection.py) read through equipment_queryset.
    assert query_calls == {"list_equipment"}
    assert not any(isinstance(node, ast.Attribute) and node.attr == "objects" for node in ast.walk(views))


def test_commands_have_atomic_transactions_and_no_transport_imports():
    application = FEATURE_ROOT / "application"
    for source_file in application.glob("*.py"):
        imports = _absolute_imports(source_file)
        assert not any("rest_framework" in name or "equipment.api" in name for name in imports)
        if source_file.name not in {"__init__.py", "_placement.py", "_category.py", "computing_profile.py"}:
            tree = _module(source_file)
            command_functions = [
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name != "__init__"
            ]
            assert any(
                any(
                    isinstance(decorator, ast.Attribute) and decorator.attr == "atomic"
                    for decorator in function.decorator_list
                )
                for function in command_functions
            )


def test_feature_package_has_canonical_layers_and_no_transitional_tree():
    assert (FEATURE_ROOT / "__init__.py").is_file()
    assert (FEATURE_ROOT / "public.py").is_file()
    assert (FEATURE_ROOT / "urls.py").is_file()
    assert (FEATURE_ROOT / "contracts.py").is_file()
    assert (FEATURE_ROOT / "exceptions.py").is_file()
    assert (FEATURE_ROOT / "application" / "__init__.py").is_file()
    assert (FEATURE_ROOT / "queries" / "__init__.py").is_file()
    assert (FEATURE_ROOT / "api" / "urls.py").is_file()
    assert (FEATURE_ROOT / "tests" / "conftest.py").is_file()
    assert (FEATURE_ROOT / "tests" / "application" / "test_assignment.py").is_file()
    assert (FEATURE_ROOT / "tests" / "application" / "test_assignment_sync.py").is_file()
    assert (FEATURE_ROOT / "tests" / "application" / "test_state.py").is_file()
    assert (FEATURE_ROOT / "tests" / "api" / "test_equipment_collection.py").is_file()
    repository_root = FEATURE_ROOT.parents[3]
    for legacy_test in (
        "test_equipment_assignment_service.py",
        "test_equipment_status_service.py",
        "test_equipment_registry.py",
        "test_equipment_subtype_api_contracts.py",
    ):
        assert not (repository_root / "tests" / "unit" / legacy_test).exists()
    for obsolete in ("base", "services", "selectors.py", "filters.py", "registry.py", "subtype_definitions.py"):
        path = FEATURE_ROOT / obsolete
        if path.is_dir():
            assert not list(path.rglob("*.py"))
        else:
            assert not path.exists()


def test_application_commands_use_frozen_inputs_and_keyword_only_actor():
    application = FEATURE_ROOT / "application"
    for name in (
        "assign_equipment.py",
        "change_state.py",
        "create_equipment.py",
        "delete_equipment.py",
        "unassign_equipment.py",
        "update_equipment.py",
    ):
        source = (application / name).read_text(encoding="utf-8-sig")
        assert "@dataclass(frozen=True" in source
        assert "*, actor" in source


def test_one_equipment_collection_and_no_category_route_sets():
    """Step 6, decision B: one collection; the category builder and its definitions are gone."""
    routes = FEATURE_ROOT / "api" / "urls.py"
    source = routes.read_text(encoding="utf-8-sig")
    assert "collection.EquipmentCollectionAPIView" in source
    assert "build_category_urlpatterns" not in source
    for removed in ("categories.py", "category_definitions.py", "category_schema.py", "registry.py"):
        assert not (FEATURE_ROOT / "api" / removed).exists(), removed


def test_kind_placeholder_modules_are_empty():
    from django.urls import Resolver404, resolve

    with pytest.raises(Resolver404):
        resolve("/equipment/computing/" + "os-names", urlconf="core.labs.features.equipment.api.urls")


def test_legacy_implementation_packages_are_removed():
    for obsolete in ("base", "services", "selectors.py", "filters.py", "registry.py", "subtype_definitions.py"):
        path = FEATURE_ROOT / obsolete
        if path.is_dir():
            assert not list(path.rglob("*.py"))
        else:
            assert not path.exists()
    packages = {path.name for path in (FEATURE_ROOT / "categories").iterdir() if path.is_dir() and path.name != "__pycache__"}
    assert packages == CATEGORIES_WITH_CODE
