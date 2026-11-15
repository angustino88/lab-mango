"""The runtime response check (response standard DOC-4) used by conftest.py."""

from core.common.openapi.response_contract import ResponseContract, to_json_schema


def _contract():
    thing = {
        "type": "object",
        "required": ["id", "owner"],
        "properties": {
            "id": {"type": "integer"},
            "owner": {"allOf": [{"$ref": "#/components/schemas/Ref"}], "nullable": True},
        },
    }
    envelope = {"type": "object", "required": ["data"], "properties": {"data": {"$ref": "#/components/schemas/Thing"}}}
    ok = {"200": {"content": {"application/json": {"schema": envelope}}}}
    return ResponseContract(
        {
            "paths": {
                "/api/things/{id}": {"get": {"responses": ok}},
                "/api/things/options": {"get": {"responses": {"200": {"description": "no schema"}}}},
            },
            "components": {
                "schemas": {
                    "Thing": thing,
                    "Ref": {
                        "type": "object",
                        "required": ["id", "name"],
                        "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                    },
                }
            },
        }
    )


def test_literal_route_wins_over_parameter():
    contract = _contract()
    assert contract.template_for("/api/things/options") == "/api/things/options"
    assert contract.template_for("/api/things/7") == "/api/things/{id}"
    assert contract.template_for("/api/unknown") is None


def test_nullable_becomes_a_json_schema_type_union():
    assert to_json_schema({"type": "string", "nullable": True}) == {"type": ["string", "null"]}
    assert to_json_schema({"allOf": [{"$ref": "#/x"}], "nullable": True}) == {
        "anyOf": [{"allOf": [{"$ref": "#/x"}]}, {"type": "null"}]
    }


def test_matching_response_has_no_violations():
    contract = _contract()
    body = {"data": {"id": 1, "owner": {"id": 2, "name": "Ada"}}}
    assert contract.violations("GET", "/api/things/1", 200, body) == []
    assert contract.violations("GET", "/api/things/1", 200, {"data": {"id": 1, "owner": None}}) == []


def test_drift_is_reported():
    contract = _contract()
    errors = contract.violations("GET", "/api/things/1", 200, {"data": {"id": "1", "owner_id": 2}})
    assert errors and any("owner" in error for error in errors)


def test_undocumented_responses_are_not_checked():
    contract = _contract()
    assert contract.violations("GET", "/api/things/options", 200, {"anything": True}) == []
    assert contract.violations("GET", "/api/things/1", 404, {"anything": True}) == []
    assert contract.violations("GET", "/api/unknown", 200, {"anything": True}) == []
