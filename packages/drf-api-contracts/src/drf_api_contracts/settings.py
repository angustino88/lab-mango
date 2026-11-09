import re
from collections.abc import Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from .types import CodeResolver, ProblemResolver

PROBLEM_JSON = "application/problem+json"
DEFAULT_PROBLEM_TYPE = "about:blank"


def default_code_value(code: Any) -> str:
    value = str(getattr(code, "value", code))
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()


def default_problem_detail(detail: Any, code: Any, status_code: int) -> str:
    if detail:
        if isinstance(detail, Mapping):
            for key in ("message", "error", "detail"):
                if detail.get(key):
                    return str(detail[key])
        return str(detail)
    if code:
        code_value = default_code_value(code)
        standard_messages = {
            "not_found": "The requested resource was not found.",
            "validation_failed": "One or more fields are invalid.",
            "invalid_query": "One or more query parameters are invalid.",
        }
        return standard_messages.get(code_value, code_value)
    return HTTPStatus(status_code).phrase


@dataclass(frozen=True, slots=True)
class ContractSettings:
    success_key: str = "data"
    pagination_meta_key: str = "meta"
    problem_content_type: str = PROBLEM_JSON
    problem_type: str = DEFAULT_PROBLEM_TYPE
    code_resolver: CodeResolver = default_code_value
    problem_detail_resolver: ProblemResolver = default_problem_detail


DEFAULT_SETTINGS = ContractSettings()
