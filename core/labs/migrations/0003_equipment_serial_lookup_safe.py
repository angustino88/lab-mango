"""Concurrent replacement for fresh databases; already-applied history is retained."""

from django.conf import settings
from django.db import migrations, models

from ._operations import AddIndexConcurrentlyWithTimeout


class Migration(migrations.Migration):
    atomic = False
    replaces = [("labs", "0003_equipment_serial_lookup")]

    dependencies = [
        ("labs", "0002_device_observations"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        AddIndexConcurrentlyWithTimeout(
            model_name="equipment",
            index=models.Index(fields=["serial_number"], name="equipment_serial_number_idx"),
        ),
    ]
