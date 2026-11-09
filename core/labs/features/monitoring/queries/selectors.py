"""Read-only selectors for the monitoring event feature."""
from __future__ import annotations

from datetime import datetime

from django.db.models import QuerySet

from core.labs.features.monitoring.exceptions import MonitoringEventNotFound
from core.labs.models import MonitoringEvent


def list_monitoring_events(
    *,
    computer_id: int | None = None,
    computer_sku: str | None = None,
    action: str | None = None,
    subject_type: str | None = None,
    bench_id: int | None = None,
    from_date: datetime | str | None = None,
    to_date: datetime | str | None = None,
) -> QuerySet[MonitoringEvent]:
    """Query list of MonitoringEvent records with optional filters."""
    qs = MonitoringEvent.objects.select_related("computer")

    if computer_id is not None:
        qs = qs.filter(computer_id=computer_id)
    if computer_sku:
        qs = qs.filter(computer__sku=computer_sku)
    if action:
        qs = qs.filter(action=action)
    if subject_type:
        qs = qs.filter(subject_type=subject_type)
    if bench_id is not None:
        qs = qs.filter(
            computer__bench_assignments__bench_id=bench_id,
            computer__bench_assignments__unassigned_at__isnull=True,
        )
    if from_date:
        qs = qs.filter(occurred_at__gte=from_date)
    if to_date:
        qs = qs.filter(occurred_at__lte=to_date)

    return qs.order_by("-occurred_at", "-id")


def get_monitoring_event(*, event_id: int) -> MonitoringEvent:
    """Retrieve a single MonitoringEvent by ID."""
    event = MonitoringEvent.objects.filter(pk=event_id).select_related("computer").first()
    if not event:
        raise MonitoringEventNotFound(f"Monitoring event with ID {event_id} not found.")
    return event


__all__ = ["get_monitoring_event", "list_monitoring_events"]
