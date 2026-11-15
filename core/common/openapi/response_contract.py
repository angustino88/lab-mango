"""Validate real HTTP responses against the committed OpenAPI schema (response standard DOC-4).

The schema gate (``contract_rules``) checks that the *documented* shapes follow the standard. This module
checks that what a view *returns* is the documented shape. The test suite runs every JSON response produced by
Django's test clients through ``ResponseContract.violations``; ``conftest.py`` wires it in.

Technical module: it reads the schema file and imports no business app.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "openapi" / "openapi-full.json"


def to_json_schema(node: Any) -> Any:
    """Translate OpenAPI 3.0 ``nullable: true`` into JSON Schema 2020-12."""
    if isinstance(node, list):
        return [to_json_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    node = {key: to_json_schema(value) for key, value in node.items()}
    if node.pop("nullable", False):
        if "type" in node:
            node["type"] = [node["type"], "null"]
        else:
            node = {"anyOf": [node, {"type": "null"}]}
    return node


@dataclass(frozen=True)
class _Route:
    template: str
    pattern: re.Pattern[str]
    literal_length: int
    parameter_count: int


class ResponseContract:
    def __init__(self, document: dict[str, Any]):
        self.document = document
        self._components = to_json_schema(document.get("components", {}))
        self._validators: dict[tuple[str, str, str], Draft202012Validator | None] = {}

    @classmethod
    def from_file(cls, path: Path = SCHEMA_PATH) -> ResponseContract:
        return cls(json.loads(path.read_text(encoding="utf-8")))

    @cached_property
    def _routes(self) -> list[_Route]:
        routes = []
        for template in self.document.get("paths", {}):
            parts = re.split(r"(\{[^}]+\})", template)
            regex = "".join("[^/]+" if part.startswith("{") else re.escape(part) for part in parts)
            routes.append(
                _Route(
                    template=template,
                    pattern=re.compile(f"^{regex}$"),
                    literal_length=sum(len(part) for part in parts if not part.startswith("{")),
                    parameter_count=sum(1 for part in parts if part.startswith("{")),
                )
            )
        # A literal segment beats a parameter: `/statuses/options` before `/statuses/{id}`.
        return sorted(routes, key=lambda route: (route.parameter_count, -route.literal_length))

    def template_for(self, path: str) -> str | None:
        for route in self._routes:
            if route.pattern.match(path):
                return route.template
        return None

    def _validator(self, template: str, method: str, status: str) -> Draft202012Validator | None:
        key = (template, method, status)
        if key not in self._validators:
            operation = self.document["paths"][template].get(method, {})
            response = operation.get("responses", {}).get(status)
            schema = ((response or {}).get("content", {}).get("application/json", {}) or {}).get("schema")
            self._validators[key] = (
                None
                if schema is None
                else Draft202012Validator({**to_json_schema(schema), "components": self._components})
            )
        return self._validators[key]

    def key(self, method: str, path: str, status: int) -> str | None:
        template = self.template_for(path)
        return None if template is None else f"{method.upper()} {template} {status}"

    def violations(self, method: str, path: str, status: int, body: Any) -> list[str]:
        """Schema errors of one JSON response; empty when it matches or the response is not documented."""
        template = self.template_for(path)
        if template is None:
            return []
        validator = self._validator(template, method.lower(), str(status))
        if validator is None:
            return []
        errors = sorted(validator.iter_errors(body), key=lambda error: list(error.absolute_path))
        return [f"{'/'.join(map(str, error.absolute_path)) or '$'}: {error.message[:200]}" for error in errors[:5]]
