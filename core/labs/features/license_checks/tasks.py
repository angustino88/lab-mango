"""Scheduled work for license checks and license expiry."""

from celery import shared_task

from core.labs.features.licenses.public import send_license_expiry_alerts

from .application.alerts import send_missing_license_alerts
from .application.retention import purge_license_check_runs


@shared_task(name="labs.licenses.send_alerts")
def send_license_alerts_task() -> dict[str, int]:
    """Daily: warnings before expiry (30, 7, 0 days) and for expected licenses no check finds."""
    expiry = send_license_expiry_alerts()
    return {
        "expiry_checked": expiry.checked,
        "expiry_sent": expiry.sent,
        "missing_sent": send_missing_license_alerts(),
    }


@shared_task(name="labs.license_checks.purge_run_history")
def purge_license_check_runs_task() -> dict[str, int]:
    return {"runs_deleted": purge_license_check_runs()}


__all__ = ("purge_license_check_runs_task", "send_license_alerts_task")
