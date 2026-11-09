"""Business error hierarchy shared by every feature (ADR 001, D6).

Feature ``exceptions.py`` modules subclass these classes and set a stable snake_case ``code``.
The classes carry no HTTP concepts; ``core.common.api.exceptions`` maps each category to a status.
Views never catch these errors: they propagate to the global DRF exception handler.

Category                        HTTP
NotFound                        404
Forbidden                       403
Conflict / VersionConflict      409  (VersionConflict: optimistic-lock failure, ``version_conflict``)
BadRequest / InvalidQuery       400  (malformed or unsupported request input)
DomainError / ValidationFailed  422  (business rule or semantic validation failure)
"""

import re
from collections.abc import Mapping
from typing import Any, ClassVar

_NAME_SUFFIX = re.compile(r"(Error|Exception)$")
_WORD_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _derive_code(class_name: str) -> str:
    """``AuditPermissionDeniedError`` -> ``audit_permission_denied``."""
    stem = _NAME_SUFFIX.sub("", class_name) or class_name
    return _WORD_BOUNDARY.sub("_", stem).lower()


class DomainError(Exception):
    """Base for every business error. Unclassified subclasses map to 422.

    A subclass that does not declare ``code`` gets a snake_case code derived from its class name,
    so every code on the wire is snake_case (ERR-2). Declare ``code`` explicitly to keep a code
    stable across a class rename.
    """

    code: ClassVar[str] = "domain_error"
    default_message: ClassVar[str] = "The request could not be completed."

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "code" not in cls.__dict__:
            cls.code = _derive_code(cls.__name__)

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.default_message)
        if code is not None:
            self.code = code
        self.details = details

    @property
    def message(self) -> str:
        return str(self.args[0]) if self.args else self.default_message


class NotFound(DomainError):
    code = "not_found"
    default_message = "The requested resource was not found."


class Forbidden(DomainError):
    code = "permission_denied"
    default_message = "You do not have permission to perform this action."


class Conflict(DomainError):
    code = "conflict"
    default_message = "The request conflicts with the current resource state."


class VersionConflict(Conflict):
    """Optimistic-lock failure: the caller's ``version`` is stale (ADR 001, Q5)."""

    code = "version_conflict"
    default_message = "The resource was modified by another request. Reload and try again."


class BadRequest(DomainError):
    code = "bad_request"
    default_message = "The request is invalid."


class InvalidQuery(BadRequest):
    code = "invalid_query"
    default_message = "One or more query parameters are invalid."


class ValidationFailed(DomainError):
    code = "validation_failed"
    default_message = "One or more fields are invalid."


__all__ = [
    "BadRequest",
    "Conflict",
    "DomainError",
    "Forbidden",
    "InvalidQuery",
    "NotFound",
    "ValidationFailed",
    "VersionConflict",
]
