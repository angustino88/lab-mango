"""Contract gate (response standard GEN-8, DOC-6).

The first test is the CI gate: the committed schema (kept equal to the code by the parity check) may contain
only violations listed in the baseline, and every listed violation must still exist, so the list only shrinks.
"""

import json
from pathlib import Path

import pytest

from core.common.openapi.contract_rules import (
    BASELINE_PATH,
    EMBEDDED_RESOURCE_EXTENSION,
    PROTOCOL_EXTENSION,
    find_violations,
    load_baseline,
)

SCHEMA_PATH = Path(__file__).resolve().parents[4] / "openapi" / "openapi-full.json"


def test_generated_schema_has_no_new_contract_violations():
    violations = find_violations(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    baseline = load_baseline()
    new = sorted(f"{v.key}: {v.message}" for v in violations if v.key not in baseline)
    fixed = sorted(baseline - {v.key for v in violations})
    assert not new, "New API contract violations (fix the code, never extend the baseline):\n" + "\n".join(new)
    assert not fixed, (
        f"Fixed violations are still listed in {BASELINE_PATH.name}; remove them so the baseline only shrinks:\n"
        + "\n".join(fixed)
    )


def _document(components, response_ref="Thing", request_ref=None):
    operation = {
        "responses": {
            "200": {"content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{response_ref}"}}}}
        }
    }
    if request_ref:
        operation["requestBody"] = {
            "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{request_ref}"}}}
        }
    return {"paths": {"/api/things": {"post": operation}}, "components": {"schemas": components}}


def _ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def _rules(document):
    return {(v.rule, v.location) for v in find_violations(document)}


def test_compliant_resource_passes():
    components = {
        "Envelope": {"type": "object", "properties": {"data": _ref("Thing")}},
        "Thing": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "readOnly": True},
                "uid": {"type": "string", "format": "uuid"},
                "owner": _ref("Ref"),
                "kind": _ref("Choice"),
                "is_active": {"type": "boolean"},
                "created_at": {"type": "string", "format": "date-time"},
                "start_date": {"type": "string", "format": "date"},
                "blocked_by": _ref("PolyRef"),
                "owner_id": {"type": "integer", "writeOnly": True},
            },
        },
        "Ref": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}}},
        "PolyRef": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "type": {"enum": ["bench", "room"]}},
        },
        "Choice": {"type": "object", "properties": {"value": {"enum": ["a", "b"]}, "label": {"type": "string"}}},
    }
    assert _rules(_document(components, response_ref="Envelope")) == set()


@pytest.mark.parametrize(
    ("properties", "expected"),
    [
        ({"name": {"type": "string"}, "id": {"type": "integer"}}, ("REL-1", "Thing")),
        ({"id": {"type": "integer"}, "name": {"type": "string"}, "uid": {"type": "string"}}, ("REL-2", "Thing")),
        (
            {"id": {"type": "integer"}, "room_id": {"type": "integer"}, "room": {"$ref": "#/components/schemas/Ref"}},
            ("REL-6", "Thing.room_id"),
        ),
        ({"id": {"type": "integer"}, "active": {"type": "boolean"}}, ("NAM-2", "Thing.active")),
        (
            {"id": {"type": "integer"}, "created": {"type": "string", "format": "date-time"}},
            ("NAM-3", "Thing.created"),
        ),
        ({"id": {"type": "integer"}, "paid_at": {"type": "string", "format": "date"}}, ("NAM-3", "Thing.paid_at")),
        ({"id": {"type": "integer"}, "state": {"type": "string", "enum": ["open"]}}, ("ENU-1", "Thing.state")),
    ],
)
def test_response_rule_violations(properties, expected):
    ref = {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}}}
    components = {"Thing": {"type": "object", "properties": properties}, "Ref": ref}
    assert expected in _rules(_document(components))


def test_id_form_reference_alone_is_allowed():
    """REL-16: `<relation>_id` is a valid reference form when it is the only form of that relation."""
    components = {
        "Thing": {"type": "object", "properties": {"id": {"type": "integer"}, "room_id": {"type": "integer"}}}
    }
    assert _rules(_document(components)) == set()


def test_relation_with_extra_keys_is_rejected_unless_embedded():
    owner = {"type": "object", "properties": {"id": {"type": "integer"}, "username": {"type": "string"}}}
    components = {
        "Thing": {"type": "object", "properties": {"id": {"type": "integer"}, "owner": _ref("Owner")}},
        "Owner": owner,
    }
    assert ("REL-3", "Thing.owner") in _rules(_document(components))

    components["Owner"] = {**owner, EMBEDDED_RESOURCE_EXTENSION: True}
    assert ("REL-3", "Thing.owner") not in _rules(_document(components))


def test_relation_arrays_are_checked():
    components = {
        "Thing": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "tags": {"type": "array", "items": _ref("Tag")}},
        },
        "Tag": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "code": {"type": "string"}},
        },
    }
    assert ("REL-3", "Thing.tags") in _rules(_document(components))


def test_protocol_components_follow_their_own_spec():
    components = {
        "Thing": {"type": "object", PROTOCOL_EXTENSION: "docs/x.md", "properties": {"backend_id": {"type": "string"}}},
    }
    assert _rules(_document(components)) == set()


def test_request_rules():
    components = {
        "Thing": {"type": "object", "properties": {"id": {"type": "integer", "readOnly": True}}},
        "ThingRequest": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "owner": _ref("Ref"),
                "name": {"type": "string"},
            },
        },
        "Ref": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}}},
    }
    rules = _rules(_document(components, request_ref="ThingRequest"))
    assert ("BDY-7", "ThingRequest.id") in rules
    assert ("TYP-10", "ThingRequest.owner") in rules
