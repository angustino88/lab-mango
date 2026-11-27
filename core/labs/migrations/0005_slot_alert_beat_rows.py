"""Slot alert jobs are built-in beat entries now (CELERY_BEAT_SCHEDULE).

``provision_booking_notification_schedules`` used to save them as disabled Periodic Tasks, and beat keeps
a row's "disabled" on startup, so those rows would keep in-app slot alerts off. Removing them lets beat
recreate them enabled. Data only; reversing is a no-op.
"""

from django.db import migrations

SLOT_ALERT_JOBS = ("bench-slot-watch-collection", "bench-slot-watch-delivery")


def remove_provisioned_slot_alert_rows(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name__in=SLOT_ALERT_JOBS, enabled=False).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("labs", "0004_bench_slot_watch"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(remove_provisioned_slot_alert_rows, migrations.RunPython.noop),
    ]
