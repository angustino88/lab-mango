"""Static tests for the locations feature's supported import surface."""

import ast
from pathlib import Path

FEATURE_ROOT = Path(__file__).resolve().parents[1]


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _absolute_imports(path: Path) -> set[str]:
    return {
        node.module
        for node in ast.walk(_module(path))
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None
    }


def _public_names(path: Path) -> list[str]:
    for node in _module(path).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path} must declare __all__")


def test_exceptions_contain_only_stable_error_types():
    exceptions_path = FEATURE_ROOT / "exceptions.py"
    assert _public_names(exceptions_path) == ["LocationConflict", "RoomConflict"]
    assert not any(
        ".application" in imported or ".queries" in imported
        for imported in _absolute_imports(exceptions_path)
    )


def test_public_module_is_the_room_station_command_and_query_facade():
    public_path = FEATURE_ROOT / "public.py"
    assert set(_public_names(public_path)) == {
        "LocationConflict", "RoomConflict",
        "get_station_type", "list_station_types",
        "change_room_lifecycle", "create_room", "delete_room", "generate_room_slots", "get_room", "get_room_for_mapping", "get_room_status_summary", "list_room_slots",
        "list_rooms", "record_room_observation", "record_room_status", "room_mapping_rows", "room_observations",
        "room_slot_mapping_rows", "room_status_history", "update_room", "change_station_lifecycle", "create_station", "create_station_slot",
        "create_station_type", "delete_station", "delete_station_slot", "delete_station_type",
        "get_station", "get_station_for_mapping", "get_station_status_summary", "list_station_slots", "list_station_types", "list_stations", "place_station",
        "record_station_status", "station_history", "station_mapping_rows", "station_reference_data", "station_slot_mapping_rows", "update_station",
        "update_station_slot", "update_station_type",
    }
    imports = {
        ("." * node.level + (node.module or "")): {alias.name for alias in node.names}
        for node in _module(public_path).body
        if isinstance(node, ast.ImportFrom)
    }
    assert imports[".rooms.application"] == {
        "change_room_lifecycle", "create_room", "delete_room", "generate_room_slots", "record_room_observation",
        "record_room_status", "update_room",
    }
    assert imports[".rooms.queries"] == {
        "get_room", "get_room_for_mapping", "list_room_slots", "list_rooms", "room_mapping_rows", "room_observations", "room_slot_mapping_rows", "room_status_history",
    }
    assert imports[".stations.application"] == {
        "change_station_lifecycle", "create_station", "create_station_slot", "create_station_type", "delete_station",
        "delete_station_slot", "delete_station_type", "place_station", "record_station_status",
        "update_station", "update_station_slot", "update_station_type",
    }
    assert imports[".stations.queries"] == {
        "get_station", "get_station_for_mapping", "get_station_type", "list_station_slots", "list_station_types", "list_stations",
        "station_history", "station_mapping_rows", "station_reference_data", "station_slot_mapping_rows",
    }
    assert imports[".rooms.queries.summaries"] == {"get_room_status_summary"}
    assert imports[".stations.queries.summaries"] == {"get_station_status_summary"}


def test_http_adapters_use_their_own_application_and_query_layers():
    for relative_path, capability in (
        ("rooms/api/views.py", "rooms"),
        ("stations/api/views.py", "stations"),
    ):
        path = FEATURE_ROOT / relative_path
        imports = _absolute_imports(path)
        assert f"core.labs.features.locations.{capability}.application" in imports
        assert f"core.labs.features.locations.{capability}.queries" in imports
        assert "core.labs.features.locations.public" not in imports


def test_nested_application_and_query_packages_export_explicit_names():
    for layer, names in (
        ("rooms/application", {
            "change_room_lifecycle", "create_room", "delete_room", "generate_room_slots", "record_room_observation",
            "record_room_status", "update_room",
        }),
        ("rooms/queries", {
            "get_room", "get_room_for_mapping", "list_room_slots", "list_rooms", "room_mapping_rows", "room_observations", "room_slot_mapping_rows", "room_status_history",
        }),
        ("stations/application", {
            "change_station_lifecycle", "create_station", "create_station_slot", "create_station_type", "delete_station",
            "delete_station_slot", "delete_station_type", "place_station", "record_station_status",
            "update_station", "update_station_slot", "update_station_type",
        }),
        ("stations/queries", {
            "get_station", "get_station_for_mapping", "get_station_type", "list_station_slots", "list_station_types", "list_stations",
            "station_history", "station_mapping_rows", "station_reference_data", "station_slot_mapping_rows",
        }),
    ):
        assert set(_public_names(FEATURE_ROOT / layer / "__init__.py")) == names
    assert set(_public_names(FEATURE_ROOT / "rooms" / "application" / "services.py")) == {
        "change_room_lifecycle", "create_room", "delete_room", "generate_room_slots", "record_room_observation",
        "record_room_status", "update_room",
    }
    assert set(_public_names(FEATURE_ROOT / "rooms" / "queries" / "selectors.py")) == {
        "get_room", "get_room_for_mapping", "list_room_slots", "list_rooms", "room_mapping_rows", "room_observations", "room_slot_mapping_rows", "room_status_history",
    }
    assert set(_public_names(FEATURE_ROOT / "stations" / "application" / "services.py")) == {
        "change_station_lifecycle", "create_station", "create_station_slot", "create_station_type", "delete_station",
        "delete_station_slot", "delete_station_type", "place_station", "record_station_status",
        "update_station", "update_station_slot", "update_station_type",
    }
    assert set(_public_names(FEATURE_ROOT / "stations" / "queries" / "selectors.py")) == {
        "get_station", "get_station_for_mapping", "get_station_type", "list_station_slots", "list_station_types", "list_stations",
        "station_history", "station_mapping_rows", "station_reference_data", "station_slot_mapping_rows",
    }


def test_locations_has_no_unowned_common_implementation_files():
    common = FEATURE_ROOT / "common"
    assert not common.exists() or not any(common.rglob("*.py"))


def test_location_root_support_modules_are_layer_owned():
    assert set(_public_names(FEATURE_ROOT / "application" / "policies.py")) == {
        "check_limit", "validate_utilities",
    }
    assert set(_public_names(FEATURE_ROOT / "application" / "services.py")) == {
        "apply_fields", "atomic_command",
    }
    assert set(_public_names(FEATURE_ROOT / "api" / "schema.py")) == {"operation"}
    assert set(_public_names(FEATURE_ROOT / "api" / "views.py")) == {"LocationAPIView"}
    assert set(_public_names(FEATURE_ROOT / "api" / "serializers.py")) == {
        "ChoiceReferenceSerializer", "LocationLifecycleWriteSerializer", "LocationStateFieldsMixin",
        "NamedReferenceSerializer",
    }
    assert set(_public_names(FEATURE_ROOT / "api" / "filters.py")) == {"location_state_filters"}
    assert set(_public_names(FEATURE_ROOT / "application" / "lifecycle.py")) == {
        "LIFECYCLE_TRANSITIONS", "apply_legacy_status", "apply_lifecycle", "ensure_lifecycle_transition",
        "record_initial",
    }


def test_api_views_do_not_duplicate_feature_http_boundary():
    assert _public_names(FEATURE_ROOT / "api" / "views.py") == ["LocationAPIView"]
    source = (FEATURE_ROOT / "api" / "views.py").read_text(encoding="utf-8-sig")
    assert "class LocationAPIView" in source


def test_root_location_queries_package_is_not_a_duplicate():
    root_queries = Path(str(FEATURE_ROOT) + "/queries")
    assert not root_queries.exists() or not list(root_queries.rglob("*.py"))


