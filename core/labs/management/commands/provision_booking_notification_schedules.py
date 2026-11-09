"""Explicit, idempotent database-beat provisioning; disabled unless --enable."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_celery_beat.models import IntervalSchedule, PeriodicTask

SCHEDULES = (
    ("bench-booking-notification-collection", "labs.bench_bookings.collect_notifications", 60),
    ("bench-booking-notification-delivery", "labs.bench_bookings.deliver_notifications", 15),
)


class Command(BaseCommand):
    help = "Provision booking notification beat jobs, disabled by default."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--enable", action="store_true")

    def handle(self, *args, **options) -> None:
        enabled = options["enable"]
        if enabled and (
            not settings.BOOKING_NOTIFICATIONS_ENABLED or settings.BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF is None
        ):
            raise CommandError("Enable notification configuration with a UTC cutoff first.")
        with transaction.atomic():
            for name, task, seconds in SCHEDULES:
                interval, _ = IntervalSchedule.objects.get_or_create(every=seconds, period=IntervalSchedule.SECONDS)
                PeriodicTask.objects.update_or_create(
                    name=name,
                    defaults={
                        "task": task,
                        "interval": interval,
                        "crontab": None,
                        "solar": None,
                        "clocked": None,
                        "enabled": enabled,
                        "queue": settings.BOOKING_NOTIFICATIONS_QUEUE,
                        "args": "[]",
                        "kwargs": "{}",
                    },
                )
        self.stdout.write("Booking notification schedules provisioned; enabled=" + str(enabled))
