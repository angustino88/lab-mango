"""Transport-neutral reference import errors."""

from core.common.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed


class ReferencePermissionDenied(Forbidden):
    code = "permission_denied"


class ReferenceNotFound(NotFound):
    code = "reference_not_found"


class ReferenceValidationFailed(ValidationFailed):
    code = "validation_failed"


class ReferenceAlreadyExists(Conflict):
    code = "reference_already_exists"


class IdempotencyKeyReuse(ValidationFailed):
    code = "idempotency_key_reuse"
