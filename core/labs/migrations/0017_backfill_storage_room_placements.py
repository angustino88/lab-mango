"""Turn ``Equipment.storage_room`` into room placements (equipment redesign, step 1).

Every non-deleted unit that has a storage room and no active placement gets an active room
placement. Units that are on a bench keep their ``storage_room`` value and get no new row (one
active placement per unit). The column itself is kept; it is dropped in a later release.
Re-running is safe: units that already have an active placement are skipped.
"""

from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    Equipment = apps.get_model("labs", "Equipment")
    Placement = apps.get_model("labs", "EquipmentAssignment")
    now = timezone.now()
    active = Placement.objects.filter(unassigned_at__isnull=True).values("equipment_id")
    units = (
        Equipment.objects.filter(deleted_at__isnull=True, storage_room__isnull=False)
        .exclude(pk__in=active)
        .values_list("pk", "storage_room_id")
        .order_by("pk")
    )
    Placement.objects.bulk_create(
        [
            Placement(equipment_id=equipment_id, room_id=room_id, assigned_at=now)
            for equipment_id, room_id in units.iterator(chunk_size=1000)
        ],
        batch_size=1000,
    )


def unbackfill(apps, schema_editor):
    """Remove every non-bench placement so ``bench`` can become NOT NULL again."""
    Placement = apps.get_model("labs", "EquipmentAssignment")
    Placement.objects.filter(bench__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("labs", "0016_equipment_placement"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
