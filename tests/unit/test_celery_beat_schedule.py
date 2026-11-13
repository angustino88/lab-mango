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
