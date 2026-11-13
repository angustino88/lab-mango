"""Record daily booking-volume and visitor snapshots for days before the nightly schedule ran."""

from datetime import date, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from core.labs.features.analytics.public import (
    MAX_DAILY_WINDOW_DAYS,
    snapshot_daily_booking_volume,
    snapshot_daily_facility_visitors,
)


class Command(BaseCommand):
    help = (
        "Recompute the daily booking-volume and distinct-visitor observations for each local day from "
        "--since up to and including --until (default: yesterday), from bookings and visit events. "
        "Idempotent: rerunning overwrites the same rows. Active user and bench totals are point-in-time "
        "counts and cannot be backfilled."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--since", type=date.fromisoformat, required=True, help="First day, YYYY-MM-DD.")
        parser.add_argument("--until", type=date.fromisoformat, default=None, help="Last day (default: yesterday).")

    def handle(self, *args: Any, **options: Any) -> None:
        yesterday = timezone.localdate() - timedelta(days=1)
        since: date = options["since"]
        until: date = options["until"] or yesterday
        if until > yesterday:
            raise CommandError("--until must be before today; today is counted live by the API.")
        if since > until:
            raise CommandError("--since must not be after --until.")
        days = (until - since).days + 1
        if days > MAX_DAILY_WINDOW_DAYS:
            raise CommandError(f"Backfill at most {MAX_DAILY_WINDOW_DAYS} days per run.")

        for offset in range(days):
            day = (since + timedelta(days=offset)).isoformat()
            snapshot_daily_booking_volume(day)
            snapshot_daily_facility_visitors(day)
        self.stdout.write(f"Recorded booking-volume and visitor snapshots for {days} day(s), {since} to {until}.")
