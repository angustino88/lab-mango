"""Make reverse accessors explicit while preserving their existing names and columns."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("labs", "0004_device_batch_default"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="deviceobservationcursor",
                    name="computer",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="deviceobservationcursor_set",
                        to="labs.equipment",
                    ),
                ),
                migrations.AlterField(
                    model_name="deviceobservationbatch",
                    name="computer",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="deviceobservationbatch_set",
                        to="labs.equipment",
                    ),
                ),
                migrations.AlterField(
                    model_name="deviceconnection",
                    name="interface",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="deviceconnection_set",
                        to="labs.equipmentinterface",
                    ),
                ),
            ],
        ),
    ]
