"""Backfill of Equipment.storage_room into room placements (labs 0017)."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

BEFORE = [("labs", "0016_equipment_placement")]
AFTER = [("labs", "0017_backfill_storage_room_placements")]


@pytest.mark.django_db(transaction=True)
def test_storage_room_becomes_room_placement_only_without_active_assignment():
    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE)
    apps = executor.loader.project_state(BEFORE).apps
    Category = apps.get_model("labs", "EquipmentCategory")
    Kind = apps.get_model("labs", "EquipmentKind")
    Equipment = apps.get_model("labs", "Equipment")
    Room = apps.get_model("labs", "Room")
    Bench = apps.get_model("labs", "Bench")
    Placement = apps.get_model("labs", "EquipmentAssignment")

    kind = Kind.objects.create(category=Category.objects.create(name="Mig", definition="Mig"), name="Mig kind")
    room = Room.objects.create(sku="MIG-R", name="Store")
    bench = Bench.objects.create(sku="MIG-B", name="Bench")
    stored = Equipment.objects.create(sku="MIG-1", name="Stored", kind=kind, storage_room=room)
    on_bench = Equipment.objects.create(sku="MIG-2", name="On bench", kind=kind, storage_room=room)
    deleted = Equipment.objects.create(
        sku="MIG-3", name="Deleted", kind=kind, storage_room=room, deleted_at=timezone.now()
    )
    nowhere = Equipment.objects.create(sku="MIG-4", name="Nowhere", kind=kind)
    Placement.objects.create(equipment=on_bench, bench=bench, assigned_at=timezone.now())

    executor = MigrationExecutor(connection)
    executor.migrate(AFTER)
    apps = executor.loader.project_state(AFTER).apps
    Placement = apps.get_model("labs", "EquipmentAssignment")
    active = {row.equipment_id: row for row in Placement.objects.filter(unassigned_at__isnull=True)}

    assert active[stored.pk].room_id == room.pk and active[stored.pk].bench_id is None
    assert active[on_bench.pk].bench_id == bench.pk
    assert deleted.pk not in active and nowhere.pk not in active

    # Reverse removes the non-bench rows so bench can be NOT NULL again.
    executor = MigrationExecutor(connection)
    executor.migrate([("labs", "0015_booking_approval_cancellation_invariants")])
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
