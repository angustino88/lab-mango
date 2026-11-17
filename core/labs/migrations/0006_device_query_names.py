"""Preserve original reverse query aliases alongside the explicit reverse accessors."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("labs", "0005_device_reverse_names"),
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
                        related_query_name="deviceobservationcursor",
                        to="labs.equipment",
                    ),
                ),
                migrations.AlterField(
                    model_name="deviceobservationbatch",
                    name="computer",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="deviceobservationbatch_set",
                        related_query_name="deviceobservationbatch",
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
                        related_query_name="deviceconnection",
                        to="labs.equipmentinterface",
                    ),
                ),
            ],
        ),
    ]
