"""Aggregate operational health only; never emit recipients or snapshot contents."""

import json

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.labs.models import BookingNotification


class Command(BaseCommand):
    help = "Print aggregate booking notification backlog and failure health."

    def handle(self, *args, **options) -> None:
        now = timezone.now()
        pending = BookingNotification.objects.filter(state="pending")
        oldest = pending.order_by("created_at").values_list("created_at", flat=True).first()
        self.stdout.write(
            json.dumps(
                {
                    "pending": pending.count(),
                    "ready": pending.filter(available_at__lte=now).count(),
                    "failed": BookingNotification.objects.filter(state="failed").count(),
                    "expired_leases": BookingNotification.objects.filter(state="leased", lease_until__lte=now).count(),
                    "oldest_pending_age_seconds": (now - oldest).total_seconds() if oldest else 0,
                }
            )
        )
