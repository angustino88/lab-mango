"""Shared validation helpers for equipment write commands."""

from core.labs.models import Equipment


def validate_equipment_model(model: type[Equipment]) -> None:
    if not isinstance(model, type) or not issubclass(model, Equipment) or model is Equipment:
        raise TypeError("Equipment write commands require a concrete Equipment model subtype.")
