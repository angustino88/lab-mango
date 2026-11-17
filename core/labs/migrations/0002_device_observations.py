"""Device connection projection, ordered cursors and idempotent batch receipts.

All three tables are new, so DDL only waits briefly on the referenced equipment and
interface tables (foreign-key validation); the lock timeout fails fast instead of queueing
behind long transactions.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("labs", "0001_initial"),
    ]

    operations = [
        # Forward: bound lock waits before the first DDL statement.
        migrations.RunSQL("SET LOCAL lock_timeout = '5s'", reverse_sql=migrations.RunSQL.noop),
        migrations.CreateModel(
            name="DeviceConnection",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("collector_key", models.CharField(max_length=32)),
                ("observation_key", models.CharField(max_length=255)),
                ("generation_key", models.UUIDField()),
                ("name", models.CharField(blank=True, max_length=255)),
                ("serial_number", models.CharField(blank=True, max_length=255)),
                ("interface_name", models.CharField(max_length=255)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("connected", "Connected"),
                            ("disconnected", "Disconnected"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "match_status",
                    models.CharField(
                        choices=[
                            ("matched", "Matched"),
                            ("unmatched", "Unmatched"),
                            ("ambiguous", "Ambiguous"),
                            ("interface_mismatch", "Interface mismatch"),
                        ],
                        max_length=24,
                    ),
                ),
                ("observed_at", models.DateTimeField()),
                ("received_at", models.DateTimeField()),
                ("first_seen_at", models.DateTimeField()),
                ("sequence", models.PositiveBigIntegerField()),
            ],
            options={
                "ordering": ("collector_key", "observation_key", "pk"),
            },
        ),
        migrations.CreateModel(
            name="DeviceObservationBatch",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("generation_key", models.UUIDField()),
                ("batch_key", models.UUIDField()),
                ("collector_key", models.CharField(max_length=32)),
                ("sequence", models.PositiveBigIntegerField()),
                ("content_hash", models.CharField(max_length=64)),
                ("is_applied", models.BooleanField(default=False)),
                ("received_at", models.DateTimeField()),
            ],
        ),
        migrations.CreateModel(
            name="DeviceObservationCursor",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("collector_key", models.CharField(max_length=32)),
                ("generation_key", models.UUIDField()),
                ("sequence", models.PositiveBigIntegerField()),
                ("is_current", models.BooleanField(default=False)),
                ("last_collected_at", models.DateTimeField()),
                ("last_received_at", models.DateTimeField()),
            ],
        ),
        migrations.AddField(
            model_name="deviceconnection",
            name="computer",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="device_connections",
                to="labs.equipment",
            ),
        ),
        migrations.AddField(
            model_name="deviceconnection",
            name="equipment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="observed_connections",
                to="labs.equipment",
            ),
        ),
        migrations.AddField(
            model_name="deviceconnection",
            name="interface",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="deviceconnection_set",
                related_query_name="deviceconnection",
                to="labs.equipmentinterface",
            ),
        ),
        migrations.AddField(
            model_name="deviceobservationbatch",
            name="computer",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="deviceobservationbatch_set",
                related_query_name="deviceobservationbatch",
                to="labs.equipment",
            ),
        ),
        migrations.AddField(
            model_name="deviceobservationcursor",
            name="computer",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="deviceobservationcursor_set",
                related_query_name="deviceobservationcursor",
                to="labs.equipment",
            ),
        ),
        migrations.AddIndex(
            model_name="deviceconnection",
            index=models.Index(
                condition=models.Q(("state", "disconnected")),
                fields=["received_at"],
                name="device_connection_detached_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="deviceconnection",
            constraint=models.UniqueConstraint(
                fields=("computer", "collector_key", "observation_key"),
                name="device_connection_observation",
            ),
        ),
        migrations.AddConstraint(
            model_name="deviceconnection",
            constraint=models.CheckConstraint(
                condition=models.Q(("sequence__gte", 1)),
                name="device_connection_sequence_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="deviceconnection",
            constraint=models.CheckConstraint(
                condition=models.Q(("state__in", ["connected", "disconnected"])),
                name="device_connection_valid_state",
            ),
        ),
        migrations.AddConstraint(
            model_name="deviceconnection",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "match_status__in",
                        ["matched", "unmatched", "ambiguous", "interface_mismatch"],
                    )
                ),
                name="device_connection_valid_match",
            ),
        ),
        migrations.AddIndex(
            model_name="deviceobservationbatch",
            index=models.Index(fields=["received_at"], name="device_batch_received_idx"),
        ),
        migrations.AddConstraint(
            model_name="deviceobservationbatch",
            constraint=models.UniqueConstraint(
                fields=("computer", "generation_key", "batch_key"),
                name="device_batch_replay_key",
            ),
        ),
        migrations.AddConstraint(
            model_name="deviceobservationbatch",
            constraint=models.UniqueConstraint(
                fields=("computer", "generation_key", "collector_key", "sequence"),
                name="device_batch_sequence",
            ),
        ),
        migrations.AddConstraint(
            model_name="deviceobservationbatch",
            constraint=models.CheckConstraint(
                condition=models.Q(("sequence__gte", 1)),
                name="device_batch_sequence_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="deviceobservationcursor",
            constraint=models.UniqueConstraint(
                fields=("computer", "collector_key"),
                name="device_cursor_computer_collector",
            ),
        ),
        migrations.AddConstraint(
            model_name="deviceobservationcursor",
            constraint=models.CheckConstraint(
                condition=models.Q(("sequence__gte", 1)),
                name="device_cursor_sequence_positive",
            ),
        ),
        # Reverse runs operations last-to-first, so bound lock waits for the DROPs here.
        migrations.RunSQL(migrations.RunSQL.noop, reverse_sql="SET LOCAL lock_timeout = '5s'"),
    ]
