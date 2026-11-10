"""Scheduled equipment reservation housekeeping (an operator schedules it in Django Celery Beat)."""

from celery import shared_task

from .application.reservations import expire_uncollected_reservations


@shared_task(name="labs.equipment.expire_uncollected_reservations")
def expire_uncollected_reservations_task() -> int:
    """Expire reserved lines whose start day has ended; safe to run repeatedly (suggested hourly)."""
    return expire_uncollected_reservations()
