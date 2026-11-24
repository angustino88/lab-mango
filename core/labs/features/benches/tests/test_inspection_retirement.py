from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

EXPANDED = ("labs", "0003_inspection_retirement_snapshot")
BACKFILLED = ("labs", "0004_backfill_bench_inspection_records")
CONTRACTED = ("labs", "0005_remove_bench_inspection_dates")


def migrate(target):
    executor = MigrationExecutor(connection)
    executor.migrate([target])
    return executor.loader.project_state([target]).apps


@pytest.mark.django_db(transaction=True)
def test_inspection_retirement_preserves_source_dates_and_canonical_service_records():
    apps = migrate(EXPANDED)
    bench_model = apps.get_model("labs", "Bench")
    record_model = apps.get_model("labs", "ResourceServiceRecord")
    content_type_model = apps.get_model("contenttypes", "ContentType")
    performed = datetime(2026, 3, 2, 9, tzinfo=UTC)
    due = performed + timedelta(days=90)
    try:
        paired = bench_model.objects.create(
            sku="INSPECT-PAIRED", last_inspected_at=performed, next_inspection_due_at=due
        )
        due_only = bench_model.objects.create(sku="INSPECT-DUE-ONLY", next_inspection_due_at=due)
        unordered = bench_model.objects.create(
            sku="INSPECT-UNORDERED",
            last_inspected_at=performed,
            next_inspection_due_at=performed - timedelta(days=1),
        )
        content_type = content_type_model.objects.get(app_label="labs", model="bench")
        existing = bench_model.objects.create(sku="INSPECT-EXISTING", last_inspected_at=performed)
        existing_record = record_model.objects.create(
            resource_content_type_id=content_type.pk,
            resource_object_id=str(existing.pk),
            kind="inspection",
            performed_at=performed,
            result="fail",
        )

        migrate(BACKFILLED)
        bench_model.objects.filter(pk=paired.pk).update(next_inspection_due_at=due + timedelta(days=1))
        with pytest.raises(RuntimeError, match="changed during backfill"):
            migrate(CONTRACTED)
        bench_model.objects.filter(pk=paired.pk).update(next_inspection_due_at=due)
        migrate(CONTRACTED)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT bench_id, performed_at, due_at
                FROM labs_bench_inspection_retirement_snapshot
                WHERE bench_id = ANY(%s)
                """,
                [[paired.pk, due_only.pk, unordered.pk]],
            )
            assert {bench_id: (last, next_due) for bench_id, last, next_due in cursor.fetchall()} == {
                paired.pk: (performed, due),
                due_only.pk: (None, due),
                unordered.pk: (performed, performed - timedelta(days=1)),
            }

        rows = record_model.objects.filter(resource_content_type_id=content_type.pk, kind="inspection")
        assert rows.get(resource_object_id=str(paired.pk)).next_due_at == due
        assert rows.get(resource_object_id=str(paired.pk)).result == "unknown"
        assert not rows.filter(resource_object_id=str(due_only.pk)).exists()
        assert rows.get(resource_object_id=str(unordered.pk)).next_due_at is None
        assert rows.get(resource_object_id=str(existing.pk)).pk == existing_record.pk
        assert rows.get(pk=existing_record.pk).result == "fail"

        migrate(EXPANDED)
        assert bench_model.objects.get(pk=due_only.pk).next_inspection_due_at == due
        assert bench_model.objects.get(pk=paired.pk).last_inspected_at == performed
        migrate(CONTRACTED)
        assert rows.filter(resource_object_id=str(paired.pk)).count() == 1
    finally:
        migrate(CONTRACTED)
