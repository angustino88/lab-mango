import pytest

from config.schema import ProjectAutoSchema
from core.common.openapi.api_catalog import (
    build_api_catalog,
    derive_operation_summary,
    normalize_schema_metadata,
    normalize_tag,
)


def test_derived_summary_omits_api_transport_prefix():
    assert derive_operation_summary("get", "/api/labs/bench-bookings", "labs_bench_bookings_retrieve") == (
        "Get Bench Bookings"
    )


def test_derived_summary_keeps_api_resource_name():
    assert derive_operation_summary("get", "/api/api-keys", "api_keys_retrieve") == "Get API Keys"


def test_normalize_tag_does_not_infer_schema_ownership():
    assert normalize_tag("Api") == "Api"
    assert normalize_tag("schema") == "Schema"


@pytest.mark.parametrize(
    ("path", "prefix", "expected"),
    [
        ("/api/labs/bench-bookings", "^/", "labs_bench_bookings_create"),
        ("/api/labs/bench-bookings", "^/api", "labs_bench_bookings_create"),
        ("/api/api-keys", "^/", "api_keys_create"),
        ("/api/api-keys", "^/api", "api_keys_create"),
        ("/api-keys", "^/", "api_keys_create"),
        ("/internal/api-keys", "^/internal", "api_keys_create"),
        ("/api/items/{item_id}/actions/approve", "^/", "items_actions_approve_create_by_item_id"),
    ],
)
def test_operation_id_removes_only_transport_mount(path, prefix, expected):
    schema = ProjectAutoSchema()
    schema.method = "POST"
    schema.path = path
    schema.path_prefix = prefix
    schema.path_regex = path

    assert schema.get_operation_id() == expected
    assert schema.path == path


def test_normalization_deduplicates_identical_root_tags():
    schema = {"tags": [{"name": "schema", "description": "Schema"}, {"name": "Schema", "description": "Schema"}]}
    normalize_schema_metadata(schema)
    assert schema["tags"] == [{"name": "Schema", "description": "Schema"}]


def test_normalization_rejects_conflicting_root_tags():
    schema = {"tags": [{"name": "schema", "description": "First"}, {"name": "Schema", "description": "Second"}]}
    with pytest.raises(ValueError, match="Conflicting OpenAPI tag definitions: Schema"):
        normalize_schema_metadata(schema)


@pytest.mark.parametrize("prefix", ["^/", "^/api"])
def test_generated_tags_remove_only_transport_mount(prefix):
    schema = ProjectAutoSchema()
    schema.path = "/api/api-keys"
    schema.path_prefix = prefix
    assert schema.get_tags() == ["api-keys"]


def test_metadata_normalization_is_idempotent_and_preserves_explicit_metadata():
    import copy

    schema = {
        "paths": {
            "/items": {"get": {
                "operationId": "custom_read", "tags": ["Items"], "summary": "Read items",
                "description": "Public documentation", "deprecated": True, "x-owner": "inventory",
                "security": [{"bearerAuth": []}], "responses": {"200": {"description": "OK"}},
            }},
        },
    }
    operation = copy.deepcopy(schema["paths"]["/items"]["get"])
    normalize_schema_metadata(schema)
    first = copy.deepcopy(schema)
    normalize_schema_metadata(schema)
    assert schema == first
    assert schema["paths"]["/items"]["get"] == operation


def test_build_api_catalog_includes_examples_and_dereferenced_schemas():
    schema = {
        "info": {"version": "2.4.0"},
        "components": {
            "schemas": {
                "Request": {
                    "type": "object",
                    "properties": {"label": {"type": "string", "example": "sample"}},
                },
                "Result": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                },
            },
            "requestBodies": {
                "Create": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Request"}}},
                }
            },
            "responses": {
                "Created": {
                    "description": "Created",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Result"}}},
                }
            },
        },
        "paths": {
            "/api/items": {
                "post": {
                    "operationId": "items_create",
                    "requestBody": {"$ref": "#/components/requestBodies/Create"},
                    "responses": {"201": {"$ref": "#/components/responses/Created"}},
                }
            }
        },
    }

    catalog = build_api_catalog(schema)

    assert catalog["title"] == "Lab Mango API Catalog"
    assert catalog["version"] == "2.4.0"
    assert catalog["total_endpoints"] == 1
    assert catalog["endpoints"][0]["request_body"]["example_payload"] == {"label": "sample"}
    assert catalog["endpoints"][0]["responses"]["201"]["example_payload"] == {"id": 1}

def test_build_api_catalog_merges_inherited_all_of_properties():
    schema = {
        "components": {
            "schemas": {
                "Base": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                    "required": ["id"],
                },
                "Extended": {
                    "allOf": [
                        {"$ref": "#/components/schemas/Base"},
                        {"type": "object", "properties": {"name": {"type": "string"}}},
                    ]
                },
            }
        },
        "paths": {
            "/api/items": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Extended"}}},
                        }
                    }
                }
            }
        },
    }

    catalog = build_api_catalog(schema)
    response = catalog["endpoints"][0]["responses"]["200"]

    assert response["schema"]["required"] == ["id"]
    assert set(response["schema"]["properties"]) == {"id", "name"}
    assert response["example_payload"] == {"id": 1, "name": "string"}


def test_build_api_catalog_handles_non_list_enum_metadata():
    schema = {
        "paths": {
            "/api/state": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "status": {
                                                "type": "string",
                                                "enum": {"description": "metadata"},
                                            }
                                        },
                                    }
                                }
                            },
                        }
                    }
                }
            }
        }
    }

    catalog = build_api_catalog(schema)

    assert catalog["endpoints"][0]["responses"]["200"]["example_payload"] == {"status": "string"}


def test_build_api_catalog_dereferences_schema_composition_arrays():
    schema = {
        "components": {
            "schemas": {
                "Base": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "Child": {"type": "object", "properties": {"name": {"type": "string"}}},
            }
        },
        "paths": {
            "/api/items": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "allOf": [
                                            {"$ref": "#/components/schemas/Base"},
                                            {"$ref": "#/components/schemas/Child"},
                                        ]
                                    }
                                }
                            },
                        }
                    }
                }
            }
        },
    }

    catalog = build_api_catalog(schema)
    response = catalog["endpoints"][0]["responses"]["200"]

    assert response["example_payload"] == {"id": 1, "name": "string"}


def test_build_api_catalog_resolves_escaped_component_refs_and_parameters():
    schema = {
        "components": {
            "parameters": {
                "Filter/Mode~1": {
                    "name": "mode",
                    "in": "query",
                    "required": True,
                    "schema": {"type": "string"},
                }
            },
            "schemas": {"Name/Value~1": {"type": "string", "example": "decoded"}},
        },
        "paths": {
            "/api/items": {
                "get": {
                    "parameters": [{"$ref": "#/components/parameters/Filter~1Mode~01"}],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {"schema": {"$ref": "#/components/schemas/Name~1Value~01"}}
                            },
                        }
                    },
                }
            }
        },
    }

    endpoint = build_api_catalog(schema)["endpoints"][0]

    assert endpoint["parameters"][0]["name"] == "mode"
    assert endpoint["parameters"][0]["in"] == "query"
    assert endpoint["responses"]["200"]["example_payload"] == "decoded"


def test_build_api_catalog_uses_explicit_media_type_examples():
    schema = {
        "components": {
            "schemas": {
                "Payload": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                }
            }
        },
        "paths": {
            "/api/items": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Payload"},
                                "example": {"value": "request example"},
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Payload"},
                                    "examples": {
                                        "named": {"summary": "response sample", "value": {"value": "response example"}}
                                    },
                                }
                            },
                        }
                    },
                }
            }
        },
    }

    endpoint = build_api_catalog(schema)["endpoints"][0]

    assert endpoint["request_body"]["example_payload"] == {"value": "request example"}
    assert endpoint["responses"]["200"]["example_payload"] == {"value": "response example"}


def test_build_api_catalog_preserves_external_example_reference():
    schema = {
        "paths": {
            "/api/items": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"type": "string"},
                                    "examples": {"external": {"externalValue": "https://example.com/value.json"}},
                                }
                            },
                        }
                    }
                }
            }
        }
    }

    endpoint = build_api_catalog(schema)["endpoints"][0]

    assert endpoint["responses"]["200"]["example_payload"] == {"externalValue": "https://example.com/value.json"}
