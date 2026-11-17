"""Record an ORM-only default without altering or rewriting the database column."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("labs", "0003_equipment_serial_lookup_safe"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="deviceobservationbatch",
                    name="is_applied",
                    field=models.BooleanField(default=False),
                ),
            ],
        ),
    ]
