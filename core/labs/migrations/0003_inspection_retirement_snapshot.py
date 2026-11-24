"""Expand: prepare a private, migration-owned snapshot and an unknown service outcome."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("labs", "0002_performance_indexes")]

    operations = [
        migrations.AlterField(
            model_name="resourceservicerecord",
            name="result",
            field=models.CharField(
                choices=[
                    ("pass", "Pass"),
                    ("fail", "Fail"),
                    ("adjusted", "Adjusted"),
                    ("unknown", "Not recorded"),
                ],
                default="pass",
                max_length=12,
            ),
        ),
        migrations.RunSQL(
            """
            CREATE TABLE labs_bench_inspection_retirement_snapshot (
                bench_id bigint PRIMARY KEY,
                performed_at timestamptz,
                due_at timestamptz
            );
            REVOKE ALL ON labs_bench_inspection_retirement_snapshot FROM PUBLIC;
            """,
            reverse_sql="DROP TABLE labs_bench_inspection_retirement_snapshot;",
        ),
    ]
