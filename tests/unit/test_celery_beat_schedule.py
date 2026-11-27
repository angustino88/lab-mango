"""Code-owned beat schedules reach django-celery-beat without a manual step (owner decision O26)."""

import pytest
from django.conf import settings
from django_celery_beat import schedulers
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from django_celery_beat.schedulers import DatabaseScheduler

from config.celery_app import app

RECONCILE = "bench-booking-status-reconciliation"
RECONCILE_TASK = "labs.bench_bookings.reconcile_statuses"


@pytest.fixture(autouse=True)
def keep_test_connection(monkeypatch):
    """The scheduler closes "old" connections, which would close the test's transaction connection."""
    monkeypatch.setattr(schedulers, "close_old_connections", lambda: None)


def start_beat() -> None:
    """What beat does at startup with the database scheduler."""
    DatabaseScheduler(app=app, lazy=True).setup_schedule()


def test_reconciliation_runs_every_minute_by_default():
    entry = settings.CELERY_BEAT_SCHEDULE[RECONCILE]

    assert entry["task"] == RECONCILE_TASK
    assert entry["schedule"] == 60.0
    assert app.conf.beat_schedule[RECONCILE]["task"] == RECONCILE_TASK


def test_worker_autodiscovery_registers_the_scheduled_task():
    app.loader.import_default_modules()  # what a worker does at startup (autodiscover_tasks)

    assert RECONCILE_TASK in app.tasks


@pytest.mark.django_db
def test_beat_startup_creates_the_periodic_task_once():
    start_beat()
    start_beat()

    task = PeriodicTask.objects.get(name=RECONCILE)
    assert (task.task, task.enabled) == (RECONCILE_TASK, True)
    assert (task.interval.every, task.interval.period) == (60, IntervalSchedule.SECONDS)
    assert PeriodicTask.objects.filter(name=RECONCILE).count() == 1


@pytest.mark.django_db
def test_an_admin_can_still_disable_it():
    start_beat()
    PeriodicTask.objects.filter(name=RECONCILE).update(enabled=False)

    start_beat()

    assert PeriodicTask.objects.get(name=RECONCILE).enabled is False


ANALYTICS_SNAPSHOTS = {
    "analytics-snapshot-daily-booking-volume": "labs.analytics.snapshot_daily_booking_volume",
    "analytics-snapshot-daily-facility-visitors": "labs.analytics.snapshot_daily_facility_visitors",
    "analytics-snapshot-daily-active-users": "labs.analytics.snapshot_daily_active_users",
    "analytics-snapshot-daily-active-benches": "labs.analytics.snapshot_daily_active_benches",
}


@pytest.mark.parametrize("name,task", ANALYTICS_SNAPSHOTS.items())
def test_analytics_snapshots_run_daily_after_local_midnight(name, task):
    schedule = settings.CELERY_BEAT_SCHEDULE[name]["schedule"]

    assert settings.CELERY_BEAT_SCHEDULE[name]["task"] == task
    assert (schedule.minute, schedule.hour) == ({15}, {0})
    app.loader.import_default_modules()
    assert task in app.tasks


@pytest.mark.django_db
def test_beat_startup_creates_the_analytics_snapshot_tasks():
    start_beat()

    tasks = dict(PeriodicTask.objects.filter(name__in=ANALYTICS_SNAPSHOTS).values_list("name", "task"))
    assert tasks == ANALYTICS_SNAPSHOTS
    assert all(PeriodicTask.objects.get(name=name).crontab.hour == "0" for name in ANALYTICS_SNAPSHOTS)


@pytest.mark.parametrize(
    "name,task",
    [
        ("licenses-send-alerts", "labs.licenses.send_alerts"),
        ("license-checks-purge-run-history", "labs.license_checks.purge_run_history"),
    ],
)
def test_license_jobs_run_daily_and_are_registered(name, task):
    assert settings.CELERY_BEAT_SCHEDULE[name]["task"] == task
    app.loader.import_default_modules()
    assert task in app.tasks


SLOT_WATCH_JOBS = {
    "bench-slot-watch-collection": ("labs.bench_bookings.collect_slot_watch_notifications", 60),
    "bench-slot-watch-delivery": ("labs.bench_bookings.deliver_slot_watch_notifications", 15),
}


@pytest.mark.django_db
def test_slot_alert_jobs_are_scheduled_without_a_manual_step():
    """Without these, "tell me when this bench is free" alerts are never found or sent."""
    app.loader.import_default_modules()
    start_beat()

    for name, (task_name, seconds) in SLOT_WATCH_JOBS.items():
        assert task_name in app.tasks
        task = PeriodicTask.objects.get(name=name)
        assert (task.task, task.enabled, task.queue) == (task_name, True, settings.BOOKING_NOTIFICATIONS_QUEUE)
        assert (task.interval.every, task.interval.period) == (seconds, IntervalSchedule.SECONDS)


@pytest.mark.django_db
def test_slot_alert_rows_saved_disabled_by_old_provisioning_come_back_enabled():
    """The provisioning command used to save these rows disabled; beat would have kept them off."""
    from importlib import import_module

    from django.apps import apps

    migration = import_module("core.labs.migrations.0005_slot_alert_beat_rows")
    interval, _ = IntervalSchedule.objects.get_or_create(every=60, period=IntervalSchedule.SECONDS)
    for name, (task_name, _seconds) in SLOT_WATCH_JOBS.items():
        PeriodicTask.objects.update_or_create(
            name=name, defaults={"task": task_name, "interval": interval, "enabled": False}
        )

    migration.remove_provisioned_slot_alert_rows(apps, None)
    start_beat()

    assert set(
        PeriodicTask.objects.filter(name__in=SLOT_WATCH_JOBS, enabled=True).values_list("name", flat=True)
    ) == set(SLOT_WATCH_JOBS)
