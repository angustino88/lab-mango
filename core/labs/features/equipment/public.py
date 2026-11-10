"""Supported external commands, queries, and stable business errors."""

from .application.assign_equipment import AssignEquipmentInput, assign_equipment
from .application.change_state import ChangeConditionInput, ChangeLifecycleInput, change_condition, change_lifecycle
from .application.create_equipment import CreateEquipmentInput, create_equipment
from .application.delete_equipment import DeleteEquipmentInput, delete_equipment
from .application.loans import (
    ExtendLoanInput,
    ExtendLoansInput,
    HandOverEquipmentInput,
    LendEquipmentBatchInput,
    ReturnEquipmentBatchInput,
    ReturnEquipmentInput,
    extend_loan,
    extend_loans,
    hand_over_equipment,
    lend_equipment_batch,
    return_equipment,
    return_equipment_batch,
)
from .application.place_equipment import (
    PlaceEquipmentInput,
    RemovePlacementInput,
    place_equipment,
    remove_placement,
)
from .application.unassign_equipment import UnassignEquipmentInput, unassign_equipment
from .application.update_equipment import UpdateEquipmentInput, update_equipment
from .categories.computing.queries import computing_activity_projection
from .contracts import ActiveEquipmentBenchAssignment
from .exceptions import (
    EquipmentAlreadyAssigned,
    EquipmentAlreadyPlaced,
    EquipmentInUse,
    EquipmentNotAvailable,
    EquipmentNotOnLoan,
    EquipmentOnLoan,
    InvalidEquipmentStatus,
    LoanManagedByBooking,
)
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
from .queries.loans import get_active_loan, get_loan_batch, list_loans
from .queries.placements import get_active_placement, has_active_placements
from .queries.state_history import equipment_state_timelines
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
    "ChangeConditionInput",
    "ChangeLifecycleInput",
    "CreateEquipmentInput",
    "DeleteEquipmentInput",
    "EquipmentAlreadyAssigned",
    "EquipmentAlreadyPlaced",
    "EquipmentNotAvailable",
    "EquipmentNotOnLoan",
    "EquipmentOnLoan",
    "ExtendLoanInput",
    "ExtendLoansInput",
    "LendEquipmentBatchInput",
    "ReturnEquipmentBatchInput",
    "extend_loans",
    "lend_equipment_batch",
    "return_equipment_batch",
    "HandOverEquipmentInput",
    "LoanManagedByBooking",
    "ReturnEquipmentInput",
    "extend_loan",
    "hand_over_equipment",
    "return_equipment",
    "EquipmentInUse",
    "InvalidEquipmentStatus",
    "PlaceEquipmentInput",
    "RemovePlacementInput",
    "equipment_state_timelines",
    "get_active_loan",
    "get_loan_batch",
    "list_loans",
    "get_active_placement",
    "has_active_placements",
    "place_equipment",
    "remove_placement",
    "inactive_equipment_candidates",
    "UnassignEquipmentInput",
    "UpdateEquipmentInput",
    "assign_equipment",
    "active_bench_assignment_mapping_rows",
    "active_equipment_bench_assignment",
    "lock_active_equipment_bench_assignment",
    "change_condition",
    "change_lifecycle",
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
