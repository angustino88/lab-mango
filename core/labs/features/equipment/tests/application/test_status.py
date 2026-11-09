import pytest

from core.labs.features.equipment.api.serializers import EquipmentStatusSerializer
from core.labs.features.equipment.application.change_equipment_status import (
    ChangeEquipmentStatusInput,
    change_equipment_status,
)
from core.labs.models.resource.equipment.assignment import EquipmentAssignment
from core.labs.models.resource.equipment.equipment import EquipmentStatus, EquipmentStatusRecord


@pytest.mark.django_db
def test_in_use_status_maps_equipment_to_bench(equipment):
    from core.labs.models.resource.bench.bench import Bench

    bench = Bench.objects.create(sku="BN-STATUS")

    record = change_equipment_status(
        ChangeEquipmentStatusInput(equipment.pk, EquipmentStatus.IN_USE, (("bench", bench.pk),)),
        actor=None,
    )

    assert record.metadata == {"bench": bench.pk, "bench_id": bench.pk}
    assert EquipmentAssignment.objects.filter(
        equipment=equipment,
        bench=bench,
        unassigned_at__isnull=True,
    ).exists()


@pytest.mark.django_db
def test_non_in_use_status_releases_equipment_from_bench(equipment):
    from core.labs.models.resource.bench.bench import Bench

    bench = Bench.objects.create(sku="BN-RELEASE")
    change_equipment_status(
        ChangeEquipmentStatusInput(equipment.pk, EquipmentStatus.IN_USE, (("bench", bench.pk),)),
        actor=None,
    )

    record = change_equipment_status(
        ChangeEquipmentStatusInput(equipment.pk, EquipmentStatus.MAINTENANCE),
        actor=None,
    )

    assert record.status == EquipmentStatus.MAINTENANCE
    assert not EquipmentAssignment.objects.filter(
        equipment=equipment,
        unassigned_at__isnull=True,
    ).exists()
    assert EquipmentAssignment.objects.filter(
        equipment=equipment,
        bench=bench,
        unassigned_at__isnull=False,
    ).exists()
    assert EquipmentStatusRecord.objects.filter(
        equipment=equipment,
        status=EquipmentStatus.MAINTENANCE,
    ).exists()


@pytest.mark.parametrize(
    ("status", "details"),
    [
        (EquipmentStatus.AVAILABLE, {"responsible_person": "Lab team", "notes": "Ready"}),
        (EquipmentStatus.IN_USE, {"responsible_person": "Lab team", "notes": "Assigned", "bench_id": 1}),
        (EquipmentStatus.IN_STORAGE, {"responsible_person": "Lab team", "notes": "Stored", "location": "Rack A", "stored_date": "2026-10-13", "condition": "Good"}),
        (EquipmentStatus.TRANSFERRED, {"responsible_person": "Lab team", "notes": "Moved", "destination": "Lab B", "transfer_date": "2026-10-13", "reason": "Relocation", "condition": "Good"}),
        (EquipmentStatus.MAINTENANCE, {"responsible_person": "Lab team", "notes": "Service", "reason": "Calibration", "start_date": "2026-10-13", "expected_end_date": "2026-10-14"}),
        (EquipmentStatus.BORROWED, {"responsible_person": "Lab team", "notes": "Loan", "borrower": "A User", "borrow_date": "2026-10-13", "expected_return_date": "2026-10-20", "purpose": "Testing", "condition": "Good"}),
        (EquipmentStatus.BROKEN, {"responsible_person": "Lab team", "notes": "Repair needed", "issue_description": "Does not start", "issue_date": "2026-10-13", "failure_cause": "Electrical fault"}),
        (EquipmentStatus.LOST, {"responsible_person": "Lab team", "notes": "Investigate", "last_known_location": "Lab", "reported_date": "2026-10-13", "description": "Inventory mismatch"}),
        (EquipmentStatus.ON_ORDER, {"responsible_person": "Lab team", "supplier": "Vendor", "expected_delivery_date": "2026-10-20"}),
    ],
)
def test_status_serializer_accepts_required_metadata(status, details):
    serializer = EquipmentStatusSerializer(data={"status": status, "details": details})

    assert serializer.is_valid(), serializer.errors


def test_status_serializer_rejects_missing_metadata():
    serializer = EquipmentStatusSerializer(data={
        "status": EquipmentStatus.BORROWED,
        "details": {"responsible_person": "Lab team"},
    })

    assert not serializer.is_valid()
    assert "borrower" in serializer.errors


def test_status_serializer_requires_common_metadata():
    serializer = EquipmentStatusSerializer(
        data={"status": EquipmentStatus.AVAILABLE, "details": {}}
    )

    assert not serializer.is_valid()
    assert "responsible_person" in serializer.errors
    assert "notes" not in serializer.errors

