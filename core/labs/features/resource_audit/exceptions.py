"""Domain exceptions for the resource audit feature."""


from core.common.domain.errors import BadRequest, DomainError, Forbidden, NotFound


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


class AuditPermissionDeniedError(Forbidden, ResourceAuditError):
    """Raised when the actor lacks permission to audit the specified resource."""

    code = "permission_denied"


__all__ = (
    "AuditPermissionDeniedError",
    "InvalidAuditResultError",
    "ResourceAuditError",
    "ResourceAuditNotFoundError",
    "ResourceNotFoundError",
)
