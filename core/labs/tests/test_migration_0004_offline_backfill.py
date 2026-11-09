"""Migration test: 0004 backfills ``offline_at`` before adding the offline check constraint."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

_BEFORE = [("labs", "0003_computing_activity_inactive_at_required")]
_AFTER = [("labs", "0004_computing_activity_agent_heartbeat_and_offline_constraint")]


@pytest.mark.django_db(transaction=True)
def test_backfill_gives_legacy_offline_rows_an_offline_at_and_leaves_heartbeat_null():
    executor = MigrationExecutor(connection)
    executor.migrate(_BEFORE)
    old_apps = executor.loader.project_state(_BEFORE).apps
    Category = old_apps.get_model("labs", "EquipmentCategory")
    Kind = old_apps.get_model("labs", "EquipmentKind")
    Computing = old_apps.get_model("labs", "ComputingEquipment")
    Activity = old_apps.get_model("labs", "ComputingActivity")

    category = Category.objects.create(name="Computing", definition="Computing equipment")
    kind = Kind.objects.create(category=category, name="Computer")
    computer = Computing.objects.create(sku="MIG-1", name="Legacy host", kind=kind)
    legacy = Activity.objects.create(computing=computer, status="offline")
    assert legacy.offline_at is None

    try:
        executor = MigrationExecutor(connection)
        executor.migrate(_AFTER)
        new_apps = executor.loader.project_state(_AFTER).apps
        migrated = new_apps.get_model("labs", "ComputingActivity").objects.get(pk=legacy.pk)

        assert migrated.offline_at is not None
        assert migrated.offline_at <= timezone.now()
        assert migrated.last_agent_report_at is None
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
