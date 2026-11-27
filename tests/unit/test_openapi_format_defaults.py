"""Schema defaults must satisfy their own ``format`` (Spectral ``oas3-valid-schema-example`` in api-lint CI)."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

FULL_SCHEMA = Path(__file__).resolve().parents[2] / "openapi" / "openapi-full.json"


def _uri_defaults(node: Any, pointer: str = "#") -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        if node.get("format") == "uri" and "default" in node:
            yield pointer, node["default"]
        for key, child in node.items():
            yield from _uri_defaults(child, f"{pointer}/{key}")
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from _uri_defaults(child, f"{pointer}/{index}")


def _is_absolute_uri(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def test_uri_format_defaults_are_valid_uris() -> None:
    schema = json.loads(FULL_SCHEMA.read_text(encoding="utf-8"))
    invalid = [(pointer, value) for pointer, value in _uri_defaults(schema) if not _is_absolute_uri(value)]
    assert invalid == []
