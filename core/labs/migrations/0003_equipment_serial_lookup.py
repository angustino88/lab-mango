"""Serial-number lookup for device matching, built without blocking equipment writes."""

from django.db import migrations, models

from ._operations import AddIndexConcurrentlyWithTimeout


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("labs", "0002_device_observations"),
    ]

    operations = [
        AddIndexConcurrentlyWithTimeout(
            model_name="equipment",
            index=models.Index(fields=["serial_number"], name="equipment_serial_number_idx"),
        ),
    ]
