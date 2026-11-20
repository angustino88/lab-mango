"""Downtime windows can stay open to lab staff bookings (``ResourceDowntime.booking_access``).

Additive and online-safe: existing rows read ``closed`` through the database default, which is the
behavior they had before (every booking blocked). No data migration.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("labs", "0003_seed_telemetry_metrics"),
    ]

    operations = [
        migrations.AddField(
            model_name="resourcedowntime",
            name="booking_access",
            field=models.CharField(
                choices=[
                    ("closed", "Closed to all bookings"),
                    ("lab_staff", "Lab staff only"),
                ],
                db_default="closed",
                default="closed",
                help_text="Who may still book the covered benches during the window.",
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="resourcedowntime",
            constraint=models.CheckConstraint(
                condition=models.Q(("booking_access__in", ["closed", "lab_staff"])),
                name="downtime_booking_access_valid",
            ),
        ),
    ]
