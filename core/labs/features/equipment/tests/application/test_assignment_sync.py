"""Regression checks for current assignment command synchronization contracts."""

from dataclasses import FrozenInstanceError

import pytest

from core.labs.features.equipment.application import AssignEquipmentInput, UnassignEquipmentInput


def test_assignment_command_inputs_are_immutable():
    assign = AssignEquipmentInput(equipment_id=1, bench_id=2)
    unassign = UnassignEquipmentInput(equipment_id=1)

    with pytest.raises((FrozenInstanceError, AttributeError)):
        assign.equipment_id = 3
    with pytest.raises((FrozenInstanceError, AttributeError)):
        unassign.equipment_id = 3
