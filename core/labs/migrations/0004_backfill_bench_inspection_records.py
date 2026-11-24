"""Backfill inspection service records in batches, keeping the exact source dates for rollback."""

from django.db import migrations, transaction

BATCH_SIZE = 500


def backfill_inspections(apps, schema_editor):
    connection = schema_editor.connection
    content_type, _ = (
        apps.get_model("contenttypes", "ContentType")
        .objects.using(connection.alias)
        .get_or_create(app_label="labs", model="bench")
    )
    last_id = None
    with connection.cursor() as cursor:
        while True:
            cursor.execute(
                "SELECT id FROM labs_bench WHERE %s::bigint IS NULL OR id > %s ORDER BY id LIMIT %s",
                [last_id, last_id, BATCH_SIZE],
            )
            ids = [row[0] for row in cursor.fetchall()]
            if not ids:
                break
            with transaction.atomic(using=connection.alias):
                cursor.execute(
                    """
                    INSERT INTO labs_bench_inspection_retirement_snapshot (bench_id, performed_at, due_at)
                    SELECT id, last_inspected_at, next_inspection_due_at
                    FROM labs_bench
                    WHERE id = ANY(%s)
                      AND (last_inspected_at IS NOT NULL OR next_inspection_due_at IS NOT NULL)
                    ON CONFLICT (bench_id) DO UPDATE
                    SET performed_at = EXCLUDED.performed_at, due_at = EXCLUDED.due_at
                    """,
                    [ids],
                )
                cursor.execute(
                    """
                    DELETE FROM labs_bench_inspection_retirement_snapshot AS snapshot
                    USING labs_bench AS bench
                    WHERE snapshot.bench_id = bench.id AND bench.id = ANY(%s)
                      AND bench.last_inspected_at IS NULL AND bench.next_inspection_due_at IS NULL
                    """,
                    [ids],
                )
                cursor.execute(
                    """
                    INSERT INTO labs_resourceservicerecord (
                        created, modified, resource_content_type_id, resource_object_id,
                        kind, performed_at, next_due_at, vendor, result, certificate_no, notes
                    )
                    SELECT CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, %s, snapshot.bench_id::text,
                        'inspection', snapshot.performed_at,
                        CASE WHEN snapshot.due_at > snapshot.performed_at THEN snapshot.due_at END,
                        '', 'unknown', '', ''
                    FROM labs_bench_inspection_retirement_snapshot AS snapshot
                    WHERE snapshot.bench_id = ANY(%s) AND snapshot.performed_at IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM labs_resourceservicerecord AS service
                          WHERE service.resource_content_type_id = %s
                            AND service.resource_object_id = snapshot.bench_id::text
                            AND service.kind = 'inspection'
                            AND service.performed_at = snapshot.performed_at
                      )
                    """,
                    [content_type.pk, ids, content_type.pk],
                )
            last_id = ids[-1]


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("labs", "0003_inspection_retirement_snapshot")]

    operations = [
        # Keep canonical service history on rollback. Matching dates prevent duplicates when reapplied.
        migrations.RunPython(backfill_inspections, migrations.RunPython.noop),
    ]
