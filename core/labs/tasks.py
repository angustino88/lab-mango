"""Labs module Celery task registry — imported for autodiscovery."""
from __future__ import annotations

# Analytics tasks
from core.labs.features.analytics.application.tasks import (
    send_storage_quota_alerts,
    snapshot_daily_active_benches,
    snapshot_daily_active_users,
    snapshot_daily_booking_volume,
    snapshot_daily_facility_visitors,
)

# Bench booking tasks
from core.labs.features.bench_bookings.tasks import (
    collect_booking_notifications_task,
    deliver_booking_notifications_task,
    reconcile_bench_booking_statuses_task,
)

# Computing activity tasks
from core.labs.features.equipment.categories.computing.tasks import (
    mark_stale_computing_activities_offline_task,
)

# Equipment reservation tasks
from core.labs.features.equipment.tasks import (
    collect_overdue_reminders_task,
    deliver_overdue_reminders_task,
    expire_uncollected_reservations_task,
)

# License alerts and license-check run retention
from core.labs.features.license_checks.tasks import purge_license_check_runs_task, send_license_alerts_task

# Device-observation retention
from core.labs.features.monitoring.tasks import purge_device_observation_history_task

__all__ = [
    "collect_overdue_reminders_task",
    "deliver_overdue_reminders_task",
    "expire_uncollected_reservations_task",
    "collect_booking_notifications_task",
    "deliver_booking_notifications_task",
    "mark_stale_computing_activities_offline_task",
    "purge_device_observation_history_task",
    "purge_license_check_runs_task",
    "send_license_alerts_task",
    "reconcile_bench_booking_statuses_task",
    "send_storage_quota_alerts",
    "snapshot_daily_active_benches",
    "snapshot_daily_active_users",
    "snapshot_daily_booking_volume",
    "snapshot_daily_facility_visitors",
]
