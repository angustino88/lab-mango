"""Regenerate only approved bench-detail GET and its reachable schema components.

Existing paths and unrelated components in the dirty module are preserved. This
does not run spectacular_modules, which rewrites every generated module.
"""

import argparse
import copy
import os
from pathlib import Path
from typing import Any

import django
import yaml

DETAIL_COMPONENT_PREFIXES = (
    "BenchDetail",
    "BenchComputingActivity",
    "BenchBookingSummary",
    "BenchReservation",
    "BenchEquipmentPage",
)
DETAIL_PATH = "/api/labs/benches/{bench_id}"
DETAIL_OPERATION_ID = "labs_benches_retrieve_by_bench_id"


def reachable_contract(module: dict[str, Any]) -> dict[str, Any]:
    """Compare only detail GET and all of its transitive local references."""
    operation = module["paths"][DETAIL_PATH]["get"]
    components: dict[str, Any] = {}
    pending = [operation]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            ref = node.get("$ref", "")
            if ref.startswith("#/components/") and ref not in components:
                _, _, section, name = ref.split("/")
                component = module["components"][section][name]
                components[ref] = component
                pending.append(component)
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return {"operation": operation, "components": components}


def assert_no_drift(committed: dict[str, Any], candidate: dict[str, Any]) -> None:
    """Fail on semantic drift, including reachable definitions, without writing."""
    assert committed["paths"][DETAIL_PATH]["get"]["operationId"] == DETAIL_OPERATION_ID, "Detail operationId drift."
    assert reachable_contract(committed) == reachable_contract(candidate), "Bench detail GET/schema drift; regenerate."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate without writing the benches module.")
    options = parser.parse_args()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    django.setup()
    from django.urls import include
    from django.urls import path as url_path
    from drf_spectacular.generators import SchemaGenerator
    from drf_spectacular.validation import validate_schema

    schema = SchemaGenerator(
        patterns=[
            url_path("api/labs/", include("core.labs.features.benches.urls")),
        ]
    ).get_schema(request=None, public=True)
    module_path = Path("openapi/labs-benches.yml")
    module = yaml.safe_load(module_path.read_text(encoding="utf-8"))
    path = DETAIL_PATH
    old_module = copy.deepcopy(module)
    module["paths"][path]["get"] = copy.deepcopy(schema["paths"][path]["get"])
    # Isolated patterns omit the root router's labs prefix during name inference.
    # Keep the established client-facing identifier, not the isolated inference.
    module["paths"][path]["get"]["operationId"] = DETAIL_OPERATION_ID
    components = module.setdefault("components", {})
    pending = [module["paths"][path]["get"]]
    visited = set()
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            ref = node.get("$ref", "")
            if ref.startswith("#/components/") and ref not in visited:
                visited.add(ref)
                _, _, section, name = ref.split("/")
                component = copy.deepcopy(schema["components"][section][name])
                existing = components.setdefault(section, {}).get(name)
                # Preserve unrelated shared definitions already in this dirty module.
                # Only the detail success envelope and newly introduced components
                # belong to this change; existing shared references remain unchanged.
                if existing is None or name.startswith(DETAIL_COMPONENT_PREFIXES):
                    components[section][name] = component
                else:
                    component = existing
                pending.append(component)
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    validate_schema(module)
    for route, path_item in old_module["paths"].items():
        for method, operation in path_item.items():
            if route != path or method != "get":
                assert module["paths"][route][method] == operation, "Unrelated operation changed."
    for section, definitions in old_module["components"].items():
        for name, definition in definitions.items():
            if not name.startswith(DETAIL_COMPONENT_PREFIXES):
                assert module["components"][section][name] == definition, "Unrelated component changed."
    if options.check:
        assert_no_drift(old_module, module)
    else:
        module_path.write_text(yaml.safe_dump(module, sort_keys=False, allow_unicode=False), encoding="utf-8")
    print(
        f"Validated bench detail GET and {len(visited)} reachable components; "
        + ("no files written." if options.check else "updated only openapi/labs-benches.yml.")
    )


if __name__ == "__main__":
    main()
