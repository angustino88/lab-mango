"""Stable business errors for equipment commands."""


from core.common.domain.errors import Conflict


class EquipmentAlreadyAssigned(Conflict):
    """Raised when equipment already has a different active bench assignment."""

    code = "equipment_already_assigned"
    default_message = "The equipment is already assigned to a bench."


class InvalidEquipmentStatus(Conflict):
    """Raised when a requested equipment status or transition is invalid."""

    code = "invalid_state_transition"
    default_message = "The requested equipment status is not allowed."


class EquipmentInUse(Conflict):
    """Raised when equipment cannot be deleted because live records still point at it."""

    code = "equipment_in_use"
    default_message = "The equipment is still assigned, licensed, or booked."


class SkuAlreadyExists(Conflict):
    """Raised when an active equipment record already uses the requested SKU."""

    code = "sku_already_exists"
    default_message = "SKU already exists."


__all__ = ["EquipmentAlreadyAssigned", "EquipmentInUse", "InvalidEquipmentStatus", "SkuAlreadyExists"]
