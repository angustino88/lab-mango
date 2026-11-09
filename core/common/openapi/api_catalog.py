"""Build a readable API catalog from a generated OpenAPI schema."""

from __future__ import annotations

from datetime import date
from typing import Any


def _resolve_ref(ref: str, components: dict[str, Any]) -> dict[str, Any] | None:
    if not ref.startswith("#/components/"):
        return None

    current: Any = {"components": components}
    for part in ref.removeprefix("#/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current if isinstance(current, dict) else None


def _dereference_object(
    value: Any,
    components: dict[str, Any],
    seen_refs: frozenset[str] = frozenset(),
    depth: int = 0,
) -> Any:
    if depth > 10 or not isinstance(value, dict):
        return value
    ref = value.get("$ref")
    if isinstance(ref, str):
        if ref in seen_refs:
            return {}
        target = _resolve_ref(ref, components)
        if target is None:
            return value
        next_seen = seen_refs | {ref}
        resolved = _dereference_object(target, components, next_seen, depth + 1)
        if isinstance(resolved, dict):
            return {
                **resolved,
                **{
                    key: _dereference_object(item, components, next_seen, depth + 1)
                    for key, item in value.items()
                    if key != "$ref"
                },
            }
        return resolved
    return {
        key: _dereference_object(item, components, seen_refs, depth + 1) if isinstance(item, dict) else item
        for key, item in value.items()
    }


def _dereference_schema(
    schema: Any,
    components: dict[str, Any],
    seen_refs: frozenset[str] = frozenset(),
    depth: int = 0,
) -> Any:
    if depth > 10:
        return {"type": "object", "description": "(max nesting depth reached)"}
    if isinstance(schema, list):
        return [_dereference_schema(item, components, seen_refs, depth + 1) for item in schema]
    if not isinstance(schema, dict):
        return schema

    if "$ref" in schema:
        ref = schema.get("$ref", "")
        if ref in seen_refs:
            return {"type": "object", "description": f"(circular reference to {ref.split('/')[-1]})"}
        target = _resolve_ref(ref, components)
        if target is None:
            return schema
        new_seen_refs = seen_refs | {ref}
        resolved = _dereference_schema(target, components, new_seen_refs, depth + 1)
        if isinstance(resolved, dict):
            result = {
                **resolved,
                **{
                    key: _dereference_schema(value, components, new_seen_refs, depth + 1)
                    for key, value in schema.items()
                    if key != "$ref"
                },
            }
        else:
            return resolved
    else:
        result = {}
        for key, value in schema.items():
            if key in {"allOf", "oneOf", "anyOf"} and isinstance(value, list):
                result[key] = [_dereference_schema(sub, components, seen_refs, depth + 1) for sub in value]
            elif isinstance(value, (dict, list)):
                result[key] = _dereference_schema(value, components, seen_refs, depth + 1)
            else:
                result[key] = value

    if isinstance(result.get("allOf"), list):
        properties: dict[str, Any] = {}
        required: list[str] = []
        for child in result["allOf"]:
            if isinstance(child, dict):
                properties.update(child.get("properties", {}))
                required.extend(child.get("required", []))
        if properties:
            properties.update(result.get("properties", {}))
            result["type"] = result.get("type", "object")
            result["properties"] = properties
            if required:
                result["required"] = sorted(set(result.get("required", []) + required))
    return result


def _example_from_schema(schema: Any, depth: int = 0) -> Any:
    if depth > 7 or not isinstance(schema, dict):
        return {} if depth > 7 else None
    if "example" in schema:
        return schema["example"]
    if isinstance(schema.get("allOf"), list):
        example: dict[str, Any] = {}
        for child in schema["allOf"]:
            child_example = _example_from_schema(child, depth + 1)
            if isinstance(child_example, dict):
                example.update(child_example)
        for name, child in schema.get("properties", {}).items():
            example[name] = _example_from_schema(child, depth + 1)
        return example
    for composition in ("oneOf", "anyOf"):
        if isinstance(schema.get(composition), list) and schema[composition]:
            return _example_from_schema(schema[composition][0], depth + 1)

    schema_type = schema.get("type")
    if not schema_type:
        schema_type = "object" if "properties" in schema else "array" if "items" in schema else None
    if schema_type == "object":
        return {name: _example_from_schema(child, depth + 1) for name, child in schema.get("properties", {}).items()}
    if schema_type == "array":
        item = _example_from_schema(schema.get("items", {}), depth + 1)
        return [item] if item is not None else []
    if schema_type == "string":
        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and enum_values:
            return enum_values[0]
        if "sku" in schema.get("title", "").lower():
            return "SKU-001"
        examples = {
            "date-time": "2026-10-20T12:00:00Z",
            "date": "2026-10-20",
            "email": "user@example.com",
            "uri": "https://example.com/resource",
            "uuid": "123e4567-e89b-12d3-a456-426614174000",
            "ipv4": "192.168.1.100",
        }
        return examples.get(schema.get("format"), schema.get("default", "string"))
    if schema_type == "integer":
        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and enum_values:
            return enum_values[0]
        return schema.get("default", 1)
    if schema_type == "number":
        return schema.get("default", 0.0)
    if schema_type == "boolean":
        return schema.get("default", True)
    if schema_type == "null":
        return None
    return None


def _media_type_example(media_type: Any, schema: Any) -> Any:
    if not isinstance(media_type, dict):
        return _example_from_schema(schema)
    if "example" in media_type:
        return media_type["example"]
    examples = media_type.get("examples")
    if isinstance(examples, dict) and examples:
        first_example = next(iter(examples.values()))
        if isinstance(first_example, dict):
            if "value" in first_example:
                return first_example["value"]
            if "externalValue" in first_example:
                return {"externalValue": first_example["externalValue"]}
    return _example_from_schema(schema)


TAG_NORMALIZATION_MAP = {
    "aad-login": "User Authentication",
    "login": "User Authentication",
    "logout": "User Authentication",
    "refresh-token": "User Authentication",
    "send-otp": "User Authentication",
    "user-groups": "User Groups",
    "users": "User Profiles",
    "notifications": "Websocket Notifications",
    "Bench bookings": "Bench Bookings",
    "Resource mappings": "Resource Mappings",
    "schema": "Schema",
}


def normalize_tag(tag: str) -> str:
    if tag in TAG_NORMALIZATION_MAP:
        return TAG_NORMALIZATION_MAP[tag]
    parts = tag.replace("-", " ").replace("_", " ").split()
    return " ".join(word.capitalize() for word in parts)


def derive_operation_summary(method: str, path: str, op_id: str) -> str:
    """Derive a clean, human-readable action-based summary (e.g. 'Get Computing Activity Summary')."""
    if not op_id:
        return f"{method.upper()} {path}"

    method = method.lower()
    special_cases = {
        "login_create": "Login",
        "logout_create": "Logout",
        "refresh_token_create": "Refresh Token",
        "send_otp_create": "Send OTP",
        "aad_login_create": "Azure AD Login",
        "aad_login_challenge_create": "Azure AD Login Challenge",
        "schema_retrieve": "Get OpenAPI Schema",
        "users_me_retrieve": "Get Current User Profile",
    }
    if op_id in special_cases:
        return special_cases[op_id]

    param_text = ""
    if "_by_" in op_id:
        base_op, param_part = op_id.rsplit("_by_", 1)
        params = param_part.split("_")
        param_names = [p.upper() if p.lower() in ("id", "sku", "uid", "otp", "aad") else p.capitalize() for p in params]
        param_text = " by " + " ".join(param_names)
        op_id = base_op

    parts = op_id.split("_")

    action = None
    if parts[-2:] == ["partial", "update"]:
        action = "Update"
        parts = parts[:-2]
    elif parts[-1] in ("retrieve", "list", "create", "update", "destroy"):
        act = parts.pop()
        if act == "destroy":
            action = "Delete"
        elif act in ("partial_update", "update"):
            action = "Update"
        elif act == "create":
            action = "Create"
        elif act == "list":
            action = "List"
        elif act == "retrieve":
            action = "Get"

    if not action:
        action = {"get": "Get", "post": "Create", "put": "Update", "patch": "Update", "delete": "Delete"}.get(
            method, method.title()
        )

    # Actions subpath handling
    if "actions" in parts:
        act_idx = parts.index("actions")
        sub_actions = parts[act_idx + 1 :]
        parts = parts[:act_idx]
        if sub_actions:
            action = " ".join(p.capitalize() for p in sub_actions)

    # Strip domain namespaces if multiple tokens remain
    if len(parts) > 1 and parts[0] in ("labs", "support_desk", "websocket"):
        parts = parts[1:]
    elif len(parts) > 1 and parts[0] in ("users", "support") and parts[1] not in ("me", "avatar"):
        parts = parts[1:]

    words = []
    for p in parts:
        if p.lower() in ("id", "sku", "uid", "aad", "otp", "rdp", "api"):
            words.append(p.upper())
        else:
            words.append(p.capitalize())

    resource_name = " ".join(words)

    if action == "Create":
        if "Assign" in resource_name:
            action = "Assign"
            resource_name = resource_name.replace("Assign", "").strip()
        elif "Upload" in resource_name or "upload" in path:
            action = "Upload"
        elif "Avatar" in resource_name:
            action = "Upload"
        elif "Favorite" in resource_name:
            action = "Favorite"
            resource_name = resource_name.replace("Favorite", "").strip()

    if not resource_name:
        return f"{action}{param_text}".strip()
    return f"{action} {resource_name}{param_text}".strip()


def normalize_schema_metadata(schema: dict[str, Any]) -> dict[str, Any]:
    """Ensure all OpenAPI tags are Title Case, every operation has a summary, and root tags are declared."""
    paths = schema.get("paths", {})
    methods = ("get", "post", "put", "patch", "delete", "options", "head")
    collected_tags: set[str] = set()

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in methods:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue

            if "tags" in operation and isinstance(operation["tags"], list):
                operation["tags"] = [normalize_tag(t) for t in operation["tags"]]
                collected_tags.update(operation["tags"])

            if not operation.get("summary"):
                op_id = operation.get("operationId", "")
                operation["summary"] = derive_operation_summary(method, path, op_id)

    existing_tag_names = set()
    schema_tags: list[dict[str, Any]] = []
    if "tags" in schema and isinstance(schema["tags"], list):
        for tag_obj in schema["tags"]:
            if isinstance(tag_obj, dict) and "name" in tag_obj:
                normalized_name = normalize_tag(tag_obj["name"])
                tag_obj = {**tag_obj, "name": normalized_name}
                if normalized_name in existing_tag_names:
                    existing = next(tag for tag in schema_tags if tag["name"] == normalized_name)
                    if existing != tag_obj:
                        raise ValueError(f"Conflicting OpenAPI tag definitions: {normalized_name}")
                    continue
                existing_tag_names.add(normalized_name)
                schema_tags.append(tag_obj)

    for tag_name in sorted(collected_tags):
        if tag_name not in existing_tag_names:
            schema_tags.append({"name": tag_name, "description": f"{tag_name} endpoints"})

    schema["tags"] = schema_tags
    return schema


def build_api_catalog(schema: dict[str, Any]) -> dict[str, Any]:
    schema = normalize_schema_metadata(schema)
    """Return endpoint details and examples without generating another schema."""
    components = schema.get("components", {})
    endpoints: list[dict[str, Any]] = []

    for path, path_item in sorted(schema.get("paths", {}).items()):
        if not isinstance(path_item, dict):
            continue
        common_parameters = path_item.get("parameters", [])
        for method in ("get", "post", "put", "patch", "delete", "options", "head"):
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue

            parameters = []
            for parameter in common_parameters + operation.get("parameters", []):
                if isinstance(parameter, dict):
                    item = _dereference_object(parameter, components)
                    parameters.append(
                        {
                            "name": item.get("name"),
                            "in": item.get("in"),
                            "required": item.get("required", False),
                            "description": item.get("description", ""),
                            "schema": item.get("schema", {}),
                        }
                    )

            request_body = None
            if "requestBody" in operation:
                body = _dereference_schema(operation["requestBody"], components)
                content = body.get("content", {})
                content_types = list(content)
                content_type = content_types[0] if content_types else "application/json"
                request_media_type = content.get(content_type, {})
                request_schema = request_media_type.get("schema", {})
                request_body = {
                    "content_type": content_type,
                    "supported_content_types": content_types,
                    "required": body.get("required", False),
                    "description": body.get("description", ""),
                    "schema": request_schema,
                    "example_payload": _media_type_example(request_media_type, request_schema),
                }

            responses = {}
            for status_code, response in operation.get("responses", {}).items():
                response = _dereference_schema(response, components)
                content = response.get("content", {})
                content_types = list(content)
                content_type = content_types[0] if content_types else "application/json"
                response_media_type = content.get(content_type, {})
                response_schema = response_media_type.get("schema", {})
                responses[str(status_code)] = {
                    "description": response.get("description", ""),
                    "content_type": content_type if content_types else None,
                    "schema": response_schema or None,
                    "example_payload": _media_type_example(response_media_type, response_schema)
                    if response_schema
                    else None,
                }

            endpoints.append(
                {
                    "endpoint": path,
                    "method": method.upper(),
                    "operation_id": operation.get("operationId", f"{method}_{path}"),
                    "summary": operation.get("summary", ""),
                    "description": operation.get("description", "").strip(),
                    "tags": operation.get("tags", []),
                    "parameters": parameters,
                    "request_body": request_body,
                    "responses": responses,
                }
            )

    return {
        "title": "Lab Mango API Catalog",
        "version": schema.get("info", {}).get("version", "1.0.0"),
        "total_endpoints": len(endpoints),
        "generated_at": date.today().isoformat(),
        "endpoints": endpoints,
    }


__all__ = ["build_api_catalog", "normalize_schema_metadata"]
