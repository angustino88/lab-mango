"""Scheduled equipment reservation and reminder jobs (an operator schedules them in Django Celery Beat)."""

from celery import shared_task

from .application.reminders import collect_overdue_reminders, deliver_overdue_reminders
from .application.reservations import expire_uncollected_reservations


@shared_task(name="labs.equipment.expire_uncollected_reservations")
def expire_uncollected_reservations_task() -> int:
    """Expire reserved lines whose start day has ended; safe to run repeatedly (suggested hourly)."""
    return expire_uncollected_reservations()


@shared_task(name="labs.equipment.collect_overdue_reminders")
def collect_overdue_reminders_task() -> int:
    """Create the current reminder slot for overdue loan slips; safe to re-run (suggested hourly)."""
    return collect_overdue_reminders()


@shared_task(name="labs.equipment.deliver_overdue_reminders", soft_time_limit=80, time_limit=90)
def deliver_overdue_reminders_task() -> dict[str, int]:
    """Send pending overdue reminders (suggested every 5 minutes)."""
    return deliver_overdue_reminders()
