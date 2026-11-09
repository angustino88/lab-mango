"""Scheduled bench booking lifecycle reconciliation."""

import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .application.state_transitions import reconcile_bench_booking_statuses


@shared_task(name="labs.bench_bookings.reconcile_statuses")
def reconcile_bench_booking_statuses_task() -> dict[str, int]:
    """Reconcile elapsed bench bookings; safe to run repeatedly."""
    return reconcile_bench_booking_statuses(now=timezone.now())


@shared_task(name="labs.bench_bookings.collect_notifications", soft_time_limit=50, time_limit=60)
def collect_booking_notifications_task(
    after_booking_id: int = 0, after_equipment_id: int = 0, page: int = 0
) -> dict[str, int]:
    from .application.notification_collection import collect_notifications

    result = collect_notifications(
        now=timezone.now(),
        after_booking_id=after_booking_id,
        after_equipment_id=after_equipment_id,
    )
    if result["booking_cursor"] >= 0 or result["equipment_cursor"] >= 0:
        collect_booking_notifications_task.apply_async(
            args=(result["booking_cursor"], result["equipment_cursor"], page + 1),
            queue=settings.BOOKING_NOTIFICATIONS_QUEUE,
        )
    logging.getLogger(__name__).info("booking_notification_collection created=%s", result["created"])
    return result


@shared_task(name="labs.bench_bookings.deliver_notifications", soft_time_limit=80, time_limit=90)
def deliver_booking_notifications_task() -> dict[str, int]:
    from .application.notification_delivery import deliver_notifications

    return deliver_notifications()
