"""Opt-in strict JSON resource parsing without changing legacy endpoints."""

import json
from typing import Any

from django.utils.http import parse_header_parameters
from rest_framework.exceptions import ParseError, UnsupportedMediaType
from rest_framework.parsers import JSONParser

from core.common.domain.errors import BadRequest, DetailMessage


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if len(pairs) > 1000:
        raise ValueError("Too many keys in an object.")
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate object key.")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON number.")


class StrictObjectJSONParser(JSONParser):
    """Reject ambiguous encodings/keys and non-object request bodies."""

    def parse(self, stream: Any, media_type: str | None = None, parser_context: Any = None) -> dict[str, Any]:
        _, parameters = parse_header_parameters(media_type or "application/json")
        if parameters.get("charset", "utf-8").lower() not in {"utf-8", "utf8"}:
            raise UnsupportedMediaType(media_type or "application/json")
        request = (parser_context or {}).get("request")
        encoding = request.headers.get("Content-Encoding", "identity") if request else "identity"
        if encoding.lower() != "identity":
            raise UnsupportedMediaType(encoding)
        try:
            raw = stream.read(262145)
            if len(raw) > 262144:
                raise ValueError("JSON body exceeds the endpoint limit.")
            depth, quoted, escaped = 0, False, False
            for character in raw.decode("utf-8"):
                if quoted:
                    if escaped:
                        escaped = False
                    elif character == "\\":
                        escaped = True
                    elif character == '"':
                        quoted = False
                elif character == '"':
                    quoted = True
                elif character in "[{":
                    depth += 1
                    if depth > 32:
                        raise BadRequest(
                            "Maximum JSON depth exceeded.",
                            code="malformed_request",
                            details={"$": DetailMessage("Maximum nesting depth is 32.", "max_depth")},
                        )
                elif character in "]}":
                    depth -= 1
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if not isinstance(value, dict):
                raise ValueError("Send a JSON object.")
            # Reject lone surrogates, including escaped surrogates accepted by json.loads.
            json.dumps(value, ensure_ascii=False).encode("utf-8")
            return value
        except (ValueError, UnicodeError, RecursionError) as error:
            raise ParseError("Request body is not a valid JSON object.") from error
