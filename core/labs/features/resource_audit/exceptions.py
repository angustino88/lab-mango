"""Domain exceptions for the resource audit feature."""


from core.common.domain.errors import BadRequest, DomainError, Forbidden, InvalidQuery, NotFound, ValidationFailed


class ResourceAuditError(DomainError):
    """Base exception for all resource audit domain errors."""


class ResourceNotFoundError(NotFound, ResourceAuditError):
    """Raised when the target resource to be audited does not exist."""

    code = "not_found"


class ResourceAuditNotFoundError(NotFound, ResourceAuditError):
    """Raised when an audit record cannot be located."""

    code = "not_found"


class InvalidAuditResultError(BadRequest, ResourceAuditError):
    """Raised when an invalid audit result is provided."""

    code = "invalid_result"
    default_message = "Select a supported audit result."


class InvalidIdempotencyKeyError(BadRequest, ResourceAuditError):
    """Raised when the Idempotency-Key header is empty or too long."""

    code = "invalid_idempotency_key"


class IdempotencyKeyReuseError(ValidationFailed, ResourceAuditError):
    """Raised when an Idempotency-Key is reused with a different request body (RW-6)."""

    code = "idempotency_key_reuse"


class InvalidCatalogCursorError(InvalidQuery, ResourceAuditError):
    """Raised when an audit catalog cursor is tampered, expired or malformed (QRY-8)."""

    code = "invalid_cursor"


class AuditPermissionDeniedError(Forbidden, ResourceAuditError):
    """Raised when the actor lacks permission to audit the specified resource."""

    code = "permission_denied"


__all__ = (
    "AuditPermissionDeniedError",
    "IdempotencyKeyReuseError",
    "InvalidAuditResultError",
    "InvalidCatalogCursorError",
    "InvalidIdempotencyKeyError",
    "ResourceAuditError",
    "ResourceAuditNotFoundError",
    "ResourceNotFoundError",
)
