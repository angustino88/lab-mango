"""Supported external commands, queries, and stable business errors."""

from .application.assign_equipment import AssignEquipmentInput, assign_equipment
from .application.change_equipment_status import ChangeEquipmentStatusInput, change_equipment_status
from .application.create_equipment import CreateEquipmentInput, create_equipment
from .application.delete_equipment import DeleteEquipmentInput, delete_equipment
from .application.unassign_equipment import UnassignEquipmentInput, unassign_equipment
from .application.update_equipment import UpdateEquipmentInput, update_equipment
from .categories.computing.queries import computing_activity_projection
from .contracts import ActiveEquipmentBenchAssignment
from .exceptions import EquipmentAlreadyAssigned, EquipmentInUse, InvalidEquipmentStatus
from .queries.equipment import (
    active_bench_assignment_mapping_rows,
    active_equipment_bench_assignment,
    equipment_mapping_rows,
    get_equipment_for_mapping,
    list_equipment,
    lock_active_equipment_bench_assignment,
    with_equipment_info,
)
from .queries.inactivity_notifications import inactive_equipment_candidates
from .queries.summaries import (
    get_computing_activity_summary,
    get_equipment_category_status_summary,
    get_equipment_status_summary,
)

__all__ = (
    "ActiveEquipmentBenchAssignment",
    "get_computing_activity_summary",
    "get_equipment_status_summary",
    "get_equipment_category_status_summary",
    "AssignEquipmentInput",
    "ChangeEquipmentStatusInput",
    "CreateEquipmentInput",
    "DeleteEquipmentInput",
    "EquipmentAlreadyAssigned",
    "EquipmentInUse",
    "InvalidEquipmentStatus",
    "inactive_equipment_candidates",
    "UnassignEquipmentInput",
    "UpdateEquipmentInput",
    "assign_equipment",
    "active_bench_assignment_mapping_rows",
    "active_equipment_bench_assignment",
    "lock_active_equipment_bench_assignment",
    "change_equipment_status",
    "computing_activity_projection",
    "create_equipment",
    "delete_equipment",
    "equipment_mapping_rows",
    "get_equipment_for_mapping",
    "list_equipment",
    "unassign_equipment",
    "update_equipment",
    "with_equipment_info",
)
