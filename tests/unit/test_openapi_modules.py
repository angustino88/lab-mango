import json
from collections import Counter

import pytest
import yaml
from django.core.management import call_command
from django.core.management.base import CommandError
from drf_api_contracts import OperationContract
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import OpenApiParameter
from rest_framework import serializers

from config.schema import ProjectAutoSchema
from core.common.api.options import IncludeIDsField
from core.common.management.commands.spectacular_modules import Command


def _query_parameters(operation):
    return [parameter for parameter in operation.get("parameters", []) if parameter["in"] == "query"]


def test_schema_endpoint_owns_tag_before_normalization():
    from drf_spectacular.views import SpectacularAPIView

    from config.features.schema.urls import SchemaAPIView

    schema = SchemaGenerator().get_schema(request=None, public=True)
    operation = schema["paths"]["/api/schema/"]["get"]
    assert operation["tags"] == ["Schema"]
    assert operation["operationId"] == "schema_retrieve"
    assert operation["summary"] == "Get OpenAPI Schema"
    assert "content negotiation" in operation["description"]
    assert "200" in operation["responses"]
    assert SchemaAPIView.get is not SpectacularAPIView.get


def test_standalone_module_preserves_inherited_security_scheme():
    schema = {
        "security": [{"bearerAuth": []}],
        "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
        "paths": {"/items": {"get": {"responses": {"200": {"description": "OK"}}}}},
    }
    module = Command()._build_module_schema(schema, schema["paths"])
    assert module["security"] == schema["security"]
    assert module["components"]["securitySchemes"] == schema["components"]["securitySchemes"]


def test_active_method_query_contracts_match_generated_openapi_exactly_once():
    """Compare only the active method's contract, not other serializers on its view."""
    generator = SchemaGenerator()
    generator._initialise_endpoints()
    endpoints = generator._get_paths_and_endpoints()
    schema = generator.get_schema(request=None, public=True)
    covered = set()
    failures = []

    for path, _path_regex, method, view in endpoints:
        contract = getattr(view, f"{method.lower()}_contract", None)
        if not isinstance(contract, OperationContract) or contract.query is None:
            continue
        assert isinstance(contract.query, (type, serializers.BaseSerializer)), (path, method, contract.query)
        query = contract.query() if isinstance(contract.query, type) else contract.query
        assert isinstance(query, serializers.Serializer), (path, method, contract.query)
        covered.add((path, method))
        operation = schema["paths"].get(path, {}).get(method.lower())
        if operation is None:
            failures.append(f"{method} {path}: active operation missing from generated schema")
            continue

        parameters = _query_parameters(operation)
        counts = Counter(parameter["name"] for parameter in parameters)
        expected = set(query.fields)
        missing = sorted(expected - counts.keys())
        unexpected = sorted(counts.keys() - expected)
        duplicated = {name: count for name, count in counts.items() if count != 1}
        if missing or unexpected or duplicated:
            failures.append(
                f"{method} {path} ({type(view).__name__}): "
                f"missing={missing}, unexpected={unexpected}, duplicated={duplicated}"
            )

    assert covered, "No active OperationContract.query operations discovered"
    assert not failures, "\n" + "\n".join(failures)


def test_generated_include_ids_parameters_use_csv_encoding_and_positive_integer_arrays():
    generator = SchemaGenerator()
    generator._initialise_endpoints()
    endpoints = generator._get_paths_and_endpoints()
    schema = generator.get_schema(request=None, public=True)
    covered = set()
    failures = []

    for path, _path_regex, method, view in endpoints:
        contract = getattr(view, f"{method.lower()}_contract", None)
        if not isinstance(contract, OperationContract) or contract.query is None:
            continue
        query = contract.query() if isinstance(contract.query, type) else contract.query
        if not isinstance(query.fields.get("include_ids"), IncludeIDsField):
            continue

        label = f"{method} {path}"
        covered.add((path, method))
        operation = schema["paths"].get(path, {}).get(method.lower())
        if operation is None:
            failures.append(f"{label}: operation missing")
            continue
        parameters = [parameter for parameter in _query_parameters(operation) if parameter["name"] == "include_ids"]
        if len(parameters) != 1:
            failures.append(f"{label}: expected one include_ids parameter, got {len(parameters)}")
            continue
        parameter = parameters[0]
        if not (
            parameter.get("style") == "form"
            and parameter.get("explode") is False
            and parameter.get("schema")
            == {
                "type": "array",
                "items": {"type": "integer", "minimum": 1},
                "maxItems": 50,
                "uniqueItems": True,
            }
        ):
            failures.append(f"{label}: incorrect include_ids parameter: {parameter}")

    assert covered, "No active query contract with an IncludeIDsField was discovered"
    assert not failures, "\n" + "\n".join(failures)


def test_explicit_include_ids_annotation_is_not_rewritten_by_csv_hook(monkeypatch):
    explicit = OpenApiParameter(
        name="include_ids",
        type=str,
        location=OpenApiParameter.QUERY,
        style="pipeDelimited",
        explode=False,
    )
    original = ProjectAutoSchema.get_override_parameters

    def with_explicit_parameter(self):
        return [*original(self), explicit]

    monkeypatch.setattr(ProjectAutoSchema, "get_override_parameters", with_explicit_parameter)
    schema = SchemaGenerator().get_schema(request=None, public=True)
    parameters = _query_parameters(schema["paths"]["/api/support/categories/options"]["get"])
    include_ids = [parameter for parameter in parameters if parameter["name"] == "include_ids"]

    assert len(include_ids) == 1
    assert include_ids[0]["style"] == "pipeDelimited"
    assert include_ids[0]["explode"] is False
    assert include_ids[0]["schema"]["type"] == "string"


def test_dashboard_query_contract_documents_all_eleven_fields_and_optional_booleans():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    parameters = _query_parameters(schema["paths"]["/api/labs/dashboard"]["get"])
    expected = {
        "activity_status",
        "bench_group",
        "has_computing",
        "is_booked",
        "is_favorite",
        "is_mapped",
        "lifecycle_status",
        "location",
        "page",
        "page_size",
        "q",
        "search",
    }

    assert Counter(parameter["name"] for parameter in parameters) == Counter({name: 1 for name in expected})
    search = next(parameter for parameter in parameters if parameter["name"] == "search")
    assert search["deprecated"] is True  # QRY-7: deprecated alias of `q` for one release
    for name in ("has_computing", "is_mapped", "is_booked", "is_favorite"):
        parameter = next(parameter for parameter in parameters if parameter["name"] == name)
        assert parameter["schema"]["type"] == "boolean", name
        assert parameter.get("required", False) is False, name


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/support/categories/options", {"include_ids", "q"}),
        ("/api/support/tickets", {"q", "status", "no_team", "ordering", "watcher_id"}),
        ("/api/user-groups", {"page", "page_size"}),
        ("/api/user-groups/{group_id}/users", {"page", "page_size"}),
        ("/api/users", {"username"}),
        ("/api/labs/analytics/lab-efficiency", {"from_date_time", "to_date_time", "order", "top"}),
        ("/api/labs/analytics/booking", {"unit"}),
        ("/api/labs/analytics/finance/summary", {"currency", "start_month", "end_month", "timezone"}),
        ("/api/labs/leaderboard/users/{id}/profile", {"start_date", "end_date"}),
        ("/api/labs/users/profile/{id}", {"start_date", "end_date"}),
    ],
)
def test_representative_query_routes_keep_their_named_fields(path, expected):
    operation = SchemaGenerator().get_schema(request=None, public=True)["paths"][path]["get"]
    counts = Counter(parameter["name"] for parameter in _query_parameters(operation))
    assert all(counts[name] == 1 for name in expected), (path, expected, counts)


def test_query_generation_preserves_explicit_override_and_other_operation_metadata():
    """Finance already has an explicit annotation for the same serializer as its contract."""
    schema = SchemaGenerator().get_schema(request=None, public=True)
    paths = schema["paths"]
    finance = paths["/api/labs/analytics/finance/summary"]["get"]
    finance_query = {parameter["name"]: parameter for parameter in _query_parameters(finance)}
    assert set(finance_query) == {"currency", "start_month", "end_month", "timezone"}
    assert all(finance_query[name]["required"] for name in ("currency", "start_month", "end_month"))
    assert "financeApiKey" in {key for alternative in finance["security"] for key in alternative}
    assert finance["tags"] == ["Analytics"]
    assert {"200", "400", "401", "403", "429"} <= finance["responses"].keys()

    members = paths["/api/user-groups/{group_id}/users"]["get"]
    assert [
        (parameter["name"], parameter["required"]) for parameter in members["parameters"] if parameter["in"] == "path"
    ] == [("group_id", True)]
    assert "group_id" not in {parameter["name"] for parameter in _query_parameters(members)}

    profile = paths["/api/labs/users/profile/{id}"]["get"]
    assert profile["deprecated"] is True
    assert profile["tags"]
    assert any(parameter["name"] == "id" and parameter["in"] == "path" for parameter in profile["parameters"])

    options = paths["/api/support/categories/options"]["get"]
    assert options["x-owner"]
    assert options["responses"]["200"]
    tickets = paths["/api/support/tickets"]
    assert tickets["get"]["security"]
    assert tickets["get"]["tags"] == tickets["post"]["tags"]
    assert tickets["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert "201" in tickets["post"]["responses"]


def test_spectacular_modules_requires_a_feature_url_module_for_every_path(monkeypatch):
    schema = {"paths": {"/unclassified": {"get": {"responses": {}}}}}
    monkeypatch.setattr(Command, "_registered_module_prefixes", lambda self: [])

    with pytest.raises(CommandError, match="not registered through a feature URL module"):
        Command()._split_schema(schema, include_untagged=False)


def test_spectacular_modules_can_write_unmatched_paths(monkeypatch):
    schema = {"paths": {"/unclassified": {"get": {"responses": {}}}}}
    monkeypatch.setattr(Command, "_registered_module_prefixes", lambda self: [])

    modules = Command()._split_schema(schema, include_untagged=True)
    assert "/unclassified" in modules["untagged.yml"]["paths"]


def test_spectacular_modules_uses_longest_feature_url_prefix(monkeypatch):
    schema = {
        "paths": {
            "/api/labs/analytics/booking": {"get": {"responses": {}}},
            "/api/labs/rooms": {"get": {"responses": {}}},
        }
    }
    monkeypatch.setattr(
        Command,
        "_registered_module_prefixes",
        lambda self: [("/api/labs/analytics", "labs-analytics.yml"), ("/api/labs", "labs.yml")],
    )

    modules = Command()._split_schema(schema, include_untagged=False)

    assert list(modules["labs-analytics.yml"]["paths"]) == ["/api/labs/analytics/booking"]
    assert list(modules["labs.yml"]["paths"]) == ["/api/labs/rooms"]


def test_spectacular_modules_writes_master_schema_with_all_paths(tmp_path):
    stale_path = tmp_path / "stale-module.yml"
    unrelated_path = tmp_path / "README.md"
    stale_path.write_text("stale", encoding="utf-8")
    unrelated_path.write_text("keep", encoding="utf-8")

    call_command("spectacular_modules", output_dir=tmp_path, include_untagged=True)

    master_schema = yaml.safe_load((tmp_path / "openapi.yml").read_text(encoding="utf-8"))
    generated_schema = SchemaGenerator().get_schema(request=None, public=True)

    assert not stale_path.exists()
    assert unrelated_path.read_text(encoding="utf-8") == "keep"
    assert set(master_schema["paths"]) == set(generated_schema["paths"])
    assert all(path_item["$ref"].startswith("./") for path_item in master_schema["paths"].values())
    assert master_schema["components"] == {"$ref": "./components.yml#/components"}
    catalog = json.loads((tmp_path / "api-catalog.json").read_text(encoding="utf-8"))
    assert catalog["total_endpoints"] == sum(
        method in path_item
        for path_item in generated_schema["paths"].values()
        for method in ("get", "post", "put", "patch", "delete", "options", "head")
    )
    assert catalog["endpoints"]

    full_json = json.loads((tmp_path / "openapi-full.json").read_text(encoding="utf-8"))
    assert set(full_json["paths"]) == set(generated_schema["paths"])
    assert "schemas" in full_json.get("components", {})
    assert "tags" in full_json and isinstance(full_json["tags"], list)
    assert not any(
        isinstance(v, dict) and "$ref" in v and v["$ref"].startswith("./")
        for v in full_json["paths"].values()
    )


def test_spectacular_modules_dry_run_does_not_create_or_modify_output_directory(tmp_path):
    output_dir = tmp_path / "openapi"
    output_dir.mkdir()
    sentinel = output_dir / "keep.json"
    sentinel.write_text("keep", encoding="utf-8")

    call_command("spectacular_modules", output_dir=output_dir, dry_run=True, include_untagged=True)

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (output_dir / "api-catalog.json").exists()


def test_spectacular_modules_no_clean_preserves_stale_yaml_files(tmp_path):
    output_dir = tmp_path / "openapi"
    output_dir.mkdir()
    stale_path = output_dir / "stale-module.yml"
    stale_path.write_text("stale", encoding="utf-8")

    call_command("spectacular_modules", output_dir=output_dir, no_clean=True, include_untagged=True)

    assert stale_path.read_text(encoding="utf-8") == "stale"


@pytest.mark.parametrize("filename", ["../openapi.yml", "nested/openapi.yml", "openapi.json"])
def test_spectacular_modules_rejects_unsafe_master_filenames(filename):
    with pytest.raises(CommandError, match="YAML filename without directory components"):
        Command()._validate_filename(filename, "master file")


def test_spectacular_modules_rejects_master_filename_that_collides_with_catalog(monkeypatch, tmp_path):
    schema = {"info": {}, "paths": {}}
    monkeypatch.setattr(SchemaGenerator, "get_schema", lambda self, request, public: schema)
    monkeypatch.setattr(Command, "_registered_module_prefixes", lambda self: [("/known", "known.yml")])

    with pytest.raises(CommandError, match="API catalog filename conflicts"):
        Command().handle(
            output_dir=tmp_path,
            include_untagged=True,
            master_file="api-catalog.json",
            dry_run=True,
            no_clean=False,
        )


def test_spectacular_modules_rejects_full_filename_that_collides_with_master(monkeypatch, tmp_path):
    schema = {"info": {}, "paths": {}}
    monkeypatch.setattr(SchemaGenerator, "get_schema", lambda self, request, public: schema)
    monkeypatch.setattr(Command, "_registered_module_prefixes", lambda self: [("/known", "known.yml")])

    with pytest.raises(CommandError, match="Full schema filename conflicts with the master document"):
        Command().handle(
            output_dir=tmp_path,
            include_untagged=True,
            master_file="openapi.yml",
            full_file="openapi.yml",
            dry_run=True,
            no_clean=False,
        )


def test_master_path_references_escape_leading_slash_and_tilde():
    schema = {"paths": {"/api/login": {}, "/api/a~b": {}}}
    modules = {
        "login.yml": {"paths": {"/api/login": {}}},
        "special.yml": {"paths": {"/api/a~b": {}}},
    }

    master_schema = Command._build_master_schema(schema, modules, "openapi.yml")

    assert master_schema["paths"]["/api/login"]["$ref"] == ("./login.yml#/paths/~1api~1login")
    assert master_schema["paths"]["/api/a~b"]["$ref"] == ("./special.yml#/paths/~1api~1a~0b")


def test_booking_count_operation_is_in_analytics_module():
    schema = SchemaGenerator().get_schema(request=None, public=True)

    modules = Command()._split_schema(schema, include_untagged=True)

    assert "/api/labs/analytics/booking" in modules["labs-analytics.yml"]["paths"]
    assert all(
        "/api/labs/analytics/booking" not in module_schema["paths"]
        for module_name, module_schema in modules.items()
        if module_name != "labs-analytics.yml"
    )


def test_modules_prune_unreferenced_components(monkeypatch):
    schema = {
        "paths": {
            "/known": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/UsedSchema"}
                                }
                            }
                        }
                    },
                    "security": [{"jwtAuth": []}],
                }
            }
        },
        "components": {
            "schemas": {
                "UsedSchema": {
                    "type": "object",
                    "properties": {
                        "nested": {"$ref": "#/components/schemas/NestedSchema"}
                    },
                },
                "NestedSchema": {"type": "string"},
                "UnrelatedSchema": {"type": "string"},
            },
            "securitySchemes": {
                "jwtAuth": {"type": "http", "scheme": "bearer"},
                "unusedAuth": {"type": "http", "scheme": "basic"},
            },
        },
    }
    monkeypatch.setattr(Command, "_registered_module_prefixes", lambda self: [("/known", "known.yml")])

    modules = Command()._split_schema(schema, include_untagged=False)

    components = modules["known.yml"]["components"]
    assert "UsedSchema" in components["schemas"]
    assert "NestedSchema" in components["schemas"]
    assert "UnrelatedSchema" not in components["schemas"]
    assert "jwtAuth" in components["securitySchemes"]
    assert "unusedAuth" not in components["securitySchemes"]


def _is_page_number_envelope(schema, components):
    while "$ref" in schema:
        schema = components[schema["$ref"].rsplit("/", 1)[-1]]
    pagination = schema.get("properties", {}).get("meta", {})
    while "$ref" in pagination:
        pagination = components[pagination["$ref"].rsplit("/", 1)[-1]]
    pagination = pagination.get("properties", {}).get("pagination", {})
    while "$ref" in pagination:
        pagination = components[pagination["$ref"].rsplit("/", 1)[-1]]
    return {"page", "page_size"} <= set(pagination.get("properties", {}))


def test_every_page_number_list_documents_page_and_page_size():
    """A paginated envelope without documented paging parameters leaves clients paging locally.

    The paginator answers a page beyond the last one with 404, so that response is documented too.
    """
    schema = SchemaGenerator().get_schema(request=None, public=True)
    components = schema["components"]["schemas"]
    paged = []
    missing = []
    for path, item in schema["paths"].items():
        operation = item.get("get")
        if operation is None:
            continue
        body = operation["responses"].get("200", {}).get("content", {}).get("application/json", {})
        if not body or not _is_page_number_envelope(body["schema"], components):
            continue
        paged.append(path)
        if "404" not in operation["responses"]:
            missing.append(f"{path} 404 (page beyond the last page)")
        parameters = {parameter["name"]: parameter for parameter in _query_parameters(operation)}
        for name in ("page", "page_size"):
            parameter = parameters.get(name)
            if parameter is None:
                missing.append(f"{path} {name}")
                continue
            assert not parameter.get("required", False), (path, name)
            assert parameter["schema"]["type"] == "integer", (path, name)
            assert parameter["schema"].get("minimum") == 1, (path, name)
        if "page_size" in parameters:
            assert parameters["page_size"]["schema"].get("maximum") == 100, path
    assert "/api/labs/equipment" in paged
    assert missing == []
