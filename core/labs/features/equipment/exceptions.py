"""Stable business errors for equipment commands."""


from core.common.domain.errors import BadRequest, Conflict, ValidationFailed


class EquipmentAlreadyAssigned(Conflict):
    """Raised when equipment already has a different active bench assignment."""

    code = "equipment_already_assigned"
    default_message = "The equipment is already assigned to a bench."


class InvalidEquipmentStatus(Conflict):
    """Raised when a requested equipment status or transition is invalid."""

    code = "invalid_state_transition"
    default_message = "The requested equipment status is not allowed."


class EquipmentAlreadyPlaced(Conflict):
    """Raised when a unit on a bench is asked to move somewhere else without leaving the bench first."""

    code = "equipment_already_placed"
    default_message = "The equipment is on a bench. Remove it from the bench first."


class EquipmentInUse(Conflict):
    """Raised when equipment cannot be deleted because live records still point at it."""

    code = "equipment_in_use"
    default_message = "The equipment is still assigned, licensed, or booked."


class EquipmentNotAvailable(Conflict):
    """Raised when a hand-over needs an available unit; ``details.reasons`` says why it is not."""

    code = "equipment_not_available"
    default_message = "The equipment is not available."


class EquipmentOnLoan(Conflict):
    """Raised when an action needs the unit back first (placement, transfer, retirement, second loan)."""

    code = "equipment_on_loan"
    default_message = "The equipment is on loan."


class EquipmentNotOnLoan(Conflict):
    """Raised when a return or extension finds no active loan."""

    code = "equipment_not_on_loan"
    default_message = "The equipment is not on loan."


class LoanManagedByBooking(Conflict):
    """Raised when a booking-linked loan is changed directly instead of through its booking."""

    code = "loan_managed_by_booking"
    default_message = "This loan belongs to a booking; change it through the booking."


class LoanIdempotencyKeyReuse(ValidationFailed):
    """Raised when an Idempotency-Key is replayed with a different request body."""

    code = "idempotency_key_reuse"
    default_message = "This Idempotency-Key was already used with a different request."


class LoanIdempotencyKeyRequired(BadRequest):
    code = "idempotency_key_required"
    default_message = "Send an Idempotency-Key header with this request."


class SkuAlreadyExists(Conflict):
    """Raised when an active equipment record already uses the requested SKU."""

    code = "sku_already_exists"
    default_message = "SKU already exists."


__all__ = [
    "EquipmentAlreadyAssigned",
    "EquipmentAlreadyPlaced",
    "EquipmentInUse",
    "EquipmentNotAvailable",
    "EquipmentNotOnLoan",
    "EquipmentOnLoan",
    "InvalidEquipmentStatus",
    "LoanIdempotencyKeyRequired",
    "LoanIdempotencyKeyReuse",
    "LoanManagedByBooking",
    "SkuAlreadyExists",
]
