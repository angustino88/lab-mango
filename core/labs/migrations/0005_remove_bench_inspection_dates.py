"""Contract: verify the snapshots under a write lock before dropping the old columns."""

from django.db import migrations


def verify_snapshot(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        cursor.execute("LOCK TABLE labs_bench IN SHARE ROW EXCLUSIVE MODE")
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM labs_bench AS bench
                LEFT JOIN labs_bench_inspection_retirement_snapshot AS snapshot ON snapshot.bench_id = bench.id
                WHERE bench.last_inspected_at IS DISTINCT FROM snapshot.performed_at
                   OR bench.next_inspection_due_at IS DISTINCT FROM snapshot.due_at
            )
            """
        )
        if cursor.fetchone()[0]:
            raise RuntimeError(
                "Bench inspection dates changed during backfill. Pause old writers and rerun migration 0004."
            )


def restore_snapshot(apps, schema_editor):
    schema_editor.execute(
        """
        UPDATE labs_bench AS bench
        SET last_inspected_at = snapshot.performed_at, next_inspection_due_at = snapshot.due_at
        FROM labs_bench_inspection_retirement_snapshot AS snapshot
        WHERE bench.id = snapshot.bench_id
        """
    )


class Migration(migrations.Migration):
    dependencies = [("labs", "0004_backfill_bench_inspection_records")]

    operations = [
        migrations.RunPython(verify_snapshot, restore_snapshot),
        migrations.RemoveField(model_name="bench", name="last_inspected_at"),
        migrations.RemoveField(model_name="bench", name="next_inspection_due_at"),
        migrations.RunSQL(migrations.RunSQL.noop, reverse_sql="SET LOCAL lock_timeout = '5s';"),
    ]
