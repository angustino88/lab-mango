"""Mechanical checks of the generated OpenAPI schema against the API standards.

Owner documents: ``docs/api/response-standard.md`` and ``docs/api/request-standard.md``. Each check names
the rule it enforces. The checks read only the generated schema; they import no business app.

A component is checked in *response context* when a response reaches it, and in *request context* when a
request body reaches it. Components shared by both are checked in both, ignoring ``writeOnly`` properties on
responses and ``readOnly`` properties on requests.

Run locally: ``uv run python -m core.common.openapi.contract_rules openapi/openapi-full.json``.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EMBEDDED_RESOURCE_EXTENSION = "x-embedded-resource"
"""Marks a component as an embedded resource (REL-15), so its nested ``id`` is not a relation."""

PROTOCOL_EXTENSION = "x-protocol-spec"
"""Marks a component as governed by a separate approved wire protocol (GEN-7); value is the spec path."""

RELATION_SHAPES = (
    ("id", "name"),
    ("id", "uid", "name"),
    ("id", "name", "type"),
    ("id", "uid", "name", "type"),
)
"""REL-3 and REL-13: the only key sequences a relation object may have."""

ALLOWED_ID_SUFFIX_NAMES = frozenset({"request_id"})
"""NAM-8: the only response keys ending in ``_id`` that are not relation inputs (ERR-4)."""

SERVER_MANAGED_WRITE_NAMES = frozenset({"id", "uid", "created_at", "updated_at", "created_by", "updated_by"})
"""BDY-7 / WRT-1: keys a request body never writes."""

_BOOLEAN_NAME = re.compile(r"^(is|has|can)_[a-z0-9_]+$")


@dataclass(frozen=True, order=True)
class Violation:
    rule: str
    location: str
    message: str

    @property
    def key(self) -> str:
        """Stable identifier used by the baseline file."""
        return f"{self.rule} {self.location}"


class _Schema:
    def __init__(self, document: dict[str, Any]):
        self.document = document
        self.components: dict[str, Any] = document.get("components", {}).get("schemas", {})

    @staticmethod
    def ref_name(node: Any) -> str | None:
        if isinstance(node, dict) and isinstance(node.get("$ref"), str):
            return node["$ref"].rsplit("/", 1)[-1]
        return None

    def resolve(self, node: Any) -> tuple[Any, str | None]:
        """Follow ``$ref`` and single-element ``allOf`` wrappers; return (schema, component name)."""
        name = None
        for _ in range(20):
            if not isinstance(node, dict):
                return node, name
            ref = self.ref_name(node)
            if ref is not None:
                name = ref
                node = self.components.get(ref, {})
                continue
            all_of = node.get("allOf")
            if isinstance(all_of, list) and len(all_of) == 1:
                node = all_of[0]
                continue
            return node, name
        return node, name

    def reachable(self, roots: Iterable[Any]) -> set[str]:
        seen: set[str] = set()
        stack = list(roots)
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                ref = self.ref_name(node)
                if ref is not None and ref not in seen:
                    seen.add(ref)
                    stack.append(self.components.get(ref, {}))
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        return seen

    def operations(self) -> Iterator[dict[str, Any]]:
        for path_item in self.document.get("paths", {}).values():
            for method, operation in path_item.items():
                if method.lower() in {"get", "put", "post", "patch", "delete", "head", "options"}:
                    yield operation


def _is_envelope(properties: dict[str, Any]) -> bool:
    keys = set(properties)
    return bool(keys) and (keys <= {"data", "meta"} or keys == {"error"})


def _is_choice_object(properties: dict[str, Any]) -> bool:
    return list(properties) == ["value", "label"]


def _is_problem_detail(properties: dict[str, Any]) -> bool:
    return "code" in properties and "message" in properties


def _is_enum(schema: Any) -> bool:
    return isinstance(schema, dict) and isinstance(schema.get("enum"), list) and schema.get("type") in (None, "string")


def _schema_types(schema: Any) -> set[str]:
    if not isinstance(schema, dict):
        return set()
    declared = schema.get("type")
    if isinstance(declared, list):
        return set(declared)
    if isinstance(declared, str):
        return {declared}
    return set()


def _object_properties(schema: Any) -> dict[str, Any] | None:
    if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
        return schema["properties"]
    return None


def _items_of(schema: Any) -> Any:
    if isinstance(schema, dict) and "array" in _schema_types(schema):
        return schema.get("items")
    return None


def _component_extension(schema: _Schema, name: str | None, extension: str) -> Any:
    if name is None:
        return None
    return schema.components.get(name, {}).get(extension)


def find_violations(document: dict[str, Any]) -> list[Violation]:
    """Return every rule violation in a generated OpenAPI document, sorted and de-duplicated."""
    schema = _Schema(document)
    response_roots = [op.get("responses", {}) for op in schema.operations()]
    request_roots = [op.get("requestBody", {}) for op in schema.operations()]
    response_components = schema.reachable(response_roots)
    request_components = schema.reachable(request_roots)

    found: set[Violation] = set()
    for name in sorted(response_components):
        component = schema.components.get(name, {})
        if component.get(PROTOCOL_EXTENSION):
            continue
        _check_response_object(schema, name, component, found)
    for name in sorted(request_components):
        component = schema.components.get(name, {})
        if component.get(PROTOCOL_EXTENSION):
            continue
        _check_request_object(schema, name, component, found)
    return sorted(found)


def _check_response_object(schema: _Schema, location: str, node: dict[str, Any], found: set[Violation]) -> None:
    properties = _object_properties(node)
    if not properties or _is_envelope(properties):
        return
    visible = {
        key: value for key, value in properties.items() if not (isinstance(value, dict) and value.get("writeOnly"))
    }
    keys = list(visible)

    if "id" in keys and keys[0] != "id":
        found.add(Violation("REL-1", location, f"`id` must be the first key, found order {keys[:4]}"))
    if "id" in keys and "uid" in keys and keys.index("uid") != 1:
        found.add(Violation("REL-2", location, "`uid` must be the second key, right after `id`"))

    choice_object = _is_choice_object(visible)
    problem_detail = _is_problem_detail(visible)
    relation_like = tuple(keys) in RELATION_SHAPES
    for key, raw in visible.items():
        resolved, ref = schema.resolve(raw)
        field = f"{location}.{key}"

        if (key.endswith("_id") or key.endswith("_ids")) and key not in ALLOWED_ID_SUFFIX_NAMES:
            found.add(
                Violation(
                    "NAM-8",
                    field,
                    "responses never expose `<relation>_id`; return a relation object (RW-2) or rename a "
                    "non-reference identifier with `_key`",
                )
            )

        types = _schema_types(resolved)
        if "boolean" in types and not _BOOLEAN_NAME.match(key):
            found.add(Violation("NAM-2", field, "boolean keys start with `is_`, `has_` or `can_`"))

        fmt = resolved.get("format") if isinstance(resolved, dict) else None
        if fmt == "date-time" and not key.endswith("_at"):
            found.add(Violation("NAM-3", field, "date-time keys end in `_at`"))
        if key.endswith("_at") and fmt != "date-time":
            found.add(Violation("NAM-3", field, "keys ending in `_at` are date-time values"))
        if fmt == "date" and not key.endswith("_date"):
            found.add(Violation("NAM-3", field, "date keys end in `_date`"))
        if key.endswith("_date") and fmt != "date":
            found.add(Violation("NAM-3", field, "keys ending in `_date` are date values"))

        exempt_enum = choice_object or (problem_detail and key == "code") or (relation_like and key == "type")
        if _is_enum(resolved) and not exempt_enum:
            found.add(Violation("ENU-1", field, "enum values are returned as `{value, label}` objects"))
        item = _items_of(resolved)
        if item is not None:
            item_resolved, item_ref = schema.resolve(item)
            if _is_enum(item_resolved):
                found.add(Violation("ENU-1", field, "enum array items are `{value, label}` objects"))
            _check_nested(schema, field, item_resolved, item_ref, found)
        else:
            _check_nested(schema, field, resolved, ref, found)


def _check_nested(schema: _Schema, field: str, resolved: Any, ref: str | None, found: set[Violation]) -> None:
    nested = _object_properties(resolved)
    if not nested:
        return
    if ref is None:
        # Inline object: check it in place, because no component carries it.
        _check_response_object(schema, field, resolved, found)
    if "id" not in nested or _component_extension(schema, ref, EMBEDDED_RESOURCE_EXTENSION):
        return
    if resolved.get(EMBEDDED_RESOURCE_EXTENSION):
        return
    nested_keys = tuple(
        key for key, value in nested.items() if not (isinstance(value, dict) and value.get("writeOnly"))
    )
    if nested_keys not in RELATION_SHAPES:
        target = ref or "inline object"
        found.add(
            Violation(
                "REL-3",
                field,
                f"relation `{target}` has keys {list(nested_keys)}; a relation is exactly `{{id, name}}` "
                f"(`uid`, `type` per REL-3/REL-13), or mark an owned child `{EMBEDDED_RESOURCE_EXTENSION}` (REL-15)",
            )
        )


def _check_request_object(schema: _Schema, location: str, node: dict[str, Any], found: set[Violation]) -> None:
    properties = _object_properties(node)
    if not properties:
        return
    for key, raw in properties.items():
        if isinstance(raw, dict) and raw.get("readOnly"):
            continue
        resolved, _ = schema.resolve(raw)
        if isinstance(resolved, dict) and resolved.get("readOnly"):
            continue
        field = f"{location}.{key}"
        if key in SERVER_MANAGED_WRITE_NAMES:
            found.add(Violation("BDY-7", field, "server-managed keys are read-only in request bodies"))
        target = _items_of(resolved)
        target_resolved = schema.resolve(target)[0] if target is not None else resolved
        nested = _object_properties(target_resolved)
        if nested and "id" in nested and _is_relation_shape(nested):
            found.add(Violation("TYP-10", field, "relations are written as `<relation>_id`, never as objects"))


def _is_relation_shape(properties: dict[str, Any]) -> bool:
    return tuple(properties) in RELATION_SHAPES


# --- baseline ----------------------------------------------------------------------------------------------

BASELINE_PATH = Path(__file__).with_name("contract_baseline.json")


def load_baseline(path: Path = BASELINE_PATH) -> set[str]:
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return set(data.get("violations", []))


def write_baseline(violations: Iterable[Violation], path: Path = BASELINE_PATH) -> None:
    keys = sorted({violation.key for violation in violations})
    payload = {
        "description": (
            "Known API contract drift, shrinking to empty. New entries are never added by hand: fix the code. "
            "See docs/architecture/decisions/007-api-contract-gate.md."
        ),
        "violations": keys,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    schema_path = Path(argv[1] if len(argv) > 1 else "openapi/openapi-full.json")
    violations = find_violations(json.loads(schema_path.read_text(encoding="utf-8")))
    if "--write-baseline" in argv:
        write_baseline(violations)
        print(f"Wrote {len(violations)} baseline entries to {BASELINE_PATH}")
        return 0
    baseline = load_baseline()
    new = [v for v in violations if v.key not in baseline]
    stale = sorted(baseline - {v.key for v in violations})
    for violation in violations:
        marker = "NEW " if violation.key not in baseline else "known"
        print(f"{marker} {violation.rule:6} {violation.location}: {violation.message}")
    print(f"\n{len(violations)} violations, {len(new)} new, {len(stale)} fixed but still in the baseline")
    return 1 if new or stale else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
