"""Equipment write commands and immutable command inputs."""

from .assign_equipment import AssignEquipmentInput, assign_equipment
from .change_state import ChangeConditionInput, ChangeLifecycleInput, change_condition, change_lifecycle
from .create_equipment import CreateEquipmentInput, create_equipment
from .delete_equipment import DeleteEquipmentInput, delete_equipment
from .loans import (
    ExtendLoanInput,
    HandOverEquipmentInput,
    ReturnEquipmentInput,
    extend_loan,
    hand_over_equipment,
    return_equipment,
)
from .place_equipment import PlaceEquipmentInput, RemovePlacementInput, place_equipment, remove_placement
from .unassign_equipment import UnassignEquipmentInput, unassign_equipment
from .update_equipment import UpdateEquipmentInput, update_equipment

__all__ = (
    "AssignEquipmentInput",
    "ChangeConditionInput",
    "ChangeLifecycleInput",
    "CreateEquipmentInput",
    "DeleteEquipmentInput",
    "ExtendLoanInput",
    "HandOverEquipmentInput",
    "ReturnEquipmentInput",
    "PlaceEquipmentInput",
    "RemovePlacementInput",
    "UnassignEquipmentInput",
    "UpdateEquipmentInput",
    "assign_equipment",
    "change_condition",
    "change_lifecycle",
    "create_equipment",
    "delete_equipment",
    "extend_loan",
    "hand_over_equipment",
    "return_equipment",
    "place_equipment",
    "remove_placement",
    "unassign_equipment",
    "update_equipment",
)
