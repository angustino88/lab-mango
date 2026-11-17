"""Paginated, joined connection projection. Freshness never uses heartbeat time.

A row is ``fresh`` when its collector's cursor is current for the row's generation and the
cursor's last applied batch was both collected and received within the freshness window.
Applied incremental batches are contiguous, so the latest batch confirms devices it did
not mention; an empty incremental batch is therefore a valid keep-alive.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TypedDict

from django.db.models import Case, CharField, Exists, IntegerField, OuterRef, QuerySet, Subquery, Value, When
from django.utils import timezone
from django_stubs_ext import WithAnnotations

from core.labs.models.monitoring import DeviceConnection, DeviceConnectionState, DeviceObservationCursor

FRESHNESS_WINDOW = timedelta(seconds=120)


class ConnectionAnnotations(TypedDict):
    is_current_generation: bool
    freshness: str


def list_device_connections(
    *, computing_id: int
) -> QuerySet[WithAnnotations[DeviceConnection, ConnectionAnnotations]]:
    """Connected devices first, then most recently observed; ties break on a stable key."""
    current = DeviceObservationCursor.objects.filter(
        computing_id=OuterRef("computing_id"),
        collector_key=OuterRef("collector_key"),
        generation_key=OuterRef("generation_key"),
        is_current=True,
    )
    cutoff = timezone.now() - FRESHNESS_WINDOW
    return (
        DeviceConnection.objects.filter(computing_id=computing_id)
        .select_related("computing", "equipment", "interface")
        .annotate(
            is_current_generation=Exists(current),
            confirmed_received_at=Subquery(current.values("last_received_at")[:1]),
            confirmed_collected_at=Subquery(current.values("last_collected_at")[:1]),
        )
        .annotate(
            freshness=Case(
                When(is_current_generation=False, then=Value("unknown")),
                When(confirmed_received_at__lt=cutoff, then=Value("stale")),
                # An old offline outbox entry is not a current physical observation.
                When(confirmed_collected_at__lt=cutoff, then=Value("stale")),
                default=Value("fresh"),
                output_field=CharField(),
            ),
            state_rank=Case(
                When(state=DeviceConnectionState.CONNECTED, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
        )
        .order_by("state_rank", "-observed_at", "collector_key", "observation_key", "pk")
    )
