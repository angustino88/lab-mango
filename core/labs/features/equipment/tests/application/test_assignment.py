import pytest
from django.core.exceptions import ObjectDoesNotExist

from core.labs.features.equipment.application.assign_equipment import AssignEquipmentInput, assign_equipment
from core.labs.features.equipment.application.unassign_equipment import UnassignEquipmentInput, unassign_equipment
from core.labs.features.equipment.queries.equipment import list_equipment
from core.labs.models.resource.bench.bench import Bench
from core.labs.models.resource.equipment.assignment import EquipmentAssignment
from core.labs.models.resource.equipment.equipment import EquipmentStatus, EquipmentStatusRecord


@pytest.mark.django_db
def test_assign_and_unassign_equipment_records_assignment_and_status(equipment):
    bench = Bench.objects.create(sku="BN-01")

    assignment = assign_equipment(AssignEquipmentInput(equipment.pk, bench.pk), actor=None)

    assert assignment.equipment_id == equipment.pk
    assert assignment.bench_id == bench.pk
    assert EquipmentAssignment.objects.filter(
        equipment=equipment,
        bench=bench,
        unassigned_at__isnull=True,
    ).exists()
    assert EquipmentStatusRecord.objects.filter(
        equipment=equipment,
        status=EquipmentStatus.IN_USE,
        metadata={"bench": bench.pk, "bench_id": bench.pk},
    ).exists()

    closed_assignment = unassign_equipment(UnassignEquipmentInput(equipment.pk), actor=None)

    assert closed_assignment is not None
    assert closed_assignment.unassigned_at is not None
    assert EquipmentStatusRecord.objects.filter(
        equipment=equipment,
        status=EquipmentStatus.AVAILABLE,
        metadata={"bench": bench.pk, "bench_id": bench.pk},
    ).exists()


@pytest.mark.django_db
def test_assign_equipment_rejects_soft_deleted_bench(equipment):
    bench = Bench.objects.create(sku="BN-01")
    bench.delete()

    with pytest.raises(ObjectDoesNotExist):
        assign_equipment(AssignEquipmentInput(equipment.pk, bench.pk), actor=None)

    assert not EquipmentAssignment.objects.filter(equipment=equipment).exists()


@pytest.mark.django_db
def test_assigned_filter_handles_equipment_with_historical_and_active_rows(equipment):
    bench = Bench.objects.create(sku="BN-HISTORY")
    assignment = assign_equipment(AssignEquipmentInput(equipment.pk, bench.pk), actor=None)
    unassign_equipment(UnassignEquipmentInput(equipment.pk), actor=None)

    assert list_equipment(assigned=False).filter(pk=equipment.pk).exists()
    assign_equipment(AssignEquipmentInput(equipment.pk, bench.pk), actor=None)

    assert list_equipment(assigned=True).filter(pk=equipment.pk).exists()
    assert not list_equipment(assigned=False).filter(pk=equipment.pk).exists()
    assignment.refresh_from_db()
    assert assignment.unassigned_at is not None


@pytest.mark.django_db
def test_unassign_missing_equipment_raises_not_found():
    with pytest.raises(ObjectDoesNotExist):
        unassign_equipment(UnassignEquipmentInput(999999), actor=None)
