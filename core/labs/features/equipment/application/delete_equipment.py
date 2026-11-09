"""Delete an equipment item using the model's soft-delete behavior."""

from dataclasses import dataclass

from django.db import transaction

from core.labs.models import Equipment

from ._validation import validate_equipment_model


@dataclass(frozen=True, slots=True)
class DeleteEquipmentInput:
    equipment_id: int
    model: type[Equipment]


@transaction.atomic
def delete_equipment(command: DeleteEquipmentInput, *, actor):
    """Lock and soft-delete one equipment model."""
    validate_equipment_model(command.model)
    instance = command.model.objects.select_for_update().get(
        pk=command.equipment_id, deleted_at__isnull=True,
    )
    instance.delete(actor=actor)
    return instance


__all__ = ("DeleteEquipmentInput", "delete_equipment")
