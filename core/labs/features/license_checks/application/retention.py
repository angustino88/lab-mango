"""Bounded purge of license-check run history (30 days).

Kept regardless of age: the newest run per check and computer (it fences stale sequences) and
every run an observation still points to (``last_run``). Each chunk is its own transaction.
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.labs.models import LicenseCheckRun, LicenseObservation

PURGE_CHUNK_SIZE = 5000


def purge_license_check_runs(*, now: datetime | None = None, max_rows: int = 200_000) -> int:
    now = now or timezone.now()
    cutoff = now - timedelta(days=settings.LICENSE_CHECK_RUN_RETENTION_DAYS)
    newest = (
        LicenseCheckRun.objects.order_by("license_check_id", "computing_id", "-sequence", "-pk")
        .distinct("license_check_id", "computing_id")
        .values("pk")
    )
    candidates = (
        LicenseCheckRun.objects.filter(received_at__lt=cutoff)
        .exclude(pk__in=newest)
        .exclude(pk__in=LicenseObservation.objects.values("last_run_id"))
    )
    deleted = 0
    while deleted < max_rows:
        with transaction.atomic():
            chunk = list(
                candidates.order_by("pk").values_list("pk", flat=True)[: min(PURGE_CHUNK_SIZE, max_rows - deleted)]
            )
            if not chunk:
                break
            count, _ = LicenseCheckRun.objects.filter(pk__in=chunk).delete()
        deleted += count
    return deleted
