"""Equipment write commands and immutable command inputs."""

from .assign_equipment import AssignEquipmentInput, assign_equipment
from .change_equipment_status import ChangeEquipmentStatusInput, change_equipment_status
from .create_equipment import CreateEquipmentInput, create_equipment
from .delete_equipment import DeleteEquipmentInput, delete_equipment
from .unassign_equipment import UnassignEquipmentInput, unassign_equipment
from .update_equipment import UpdateEquipmentInput, update_equipment

__all__ = (
    "AssignEquipmentInput",
    "ChangeEquipmentStatusInput",
    "CreateEquipmentInput",
    "DeleteEquipmentInput",
    "UnassignEquipmentInput",
    "UpdateEquipmentInput",
    "assign_equipment",
    "change_equipment_status",
    "create_equipment",
    "delete_equipment",
    "unassign_equipment",
    "update_equipment",
)
