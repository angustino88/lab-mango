"""Stable procurement business errors."""


from core.common.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed, VersionConflict


class PurchaseAllocationConflict(Conflict):
    """Raised when a purchase item's quantity or allocated amount is exceeded."""

    code = "purchase_allocation_conflict"


class PurchaseDraftConflict(Conflict):
    """Raised when a purchase or line cannot be changed in its current state."""

    code = "purchase_draft_conflict"


class PurchaseNotFound(NotFound):
    """A purchase or child line is missing or outside the addressed aggregate."""

    code = "not_found"


class PurchaseETagRequired(Conflict):
    """A draft mutation did not include its required If-Match condition."""

    code = "precondition_required"
    status_code = 428


class PurchasePreconditionFailed(VersionConflict):
    """The supplied strong ETag does not match the current version."""

    code = "precondition_failed"
    status_code = 412


class PurchaseMachineWriteForbidden(Forbidden):
    """Machine credentials cannot mutate drafts without auditable scoped identity."""

    code = "permission_denied"


class PurchaseDraftValidationFailed(ValidationFailed):
    """A draft mutation violates purchase-specific validation rules."""

    code = "validation_failed"


__all__ = [
    "PurchaseAllocationConflict",
    "PurchaseDraftConflict",
    "PurchaseDraftValidationFailed",
    "PurchaseETagRequired",
    "PurchaseMachineWriteForbidden",
    "PurchaseNotFound",
    "PurchasePreconditionFailed",
]
