"""Paginated, joined connection projection. Freshness never uses heartbeat time."""

from __future__ import annotations

from datetime import timedelta
from typing import TypedDict

from django.db.models import Case, CharField, Exists, OuterRef, QuerySet, Value, When
from django.utils import timezone
from django_stubs_ext import WithAnnotations

from core.labs.models.monitoring import DeviceConnection, DeviceObservationCursor


class ConnectionAnnotations(TypedDict):
    is_current_generation: bool
    freshness: str


def list_device_connections(*, computer_id: int) -> QuerySet[WithAnnotations[DeviceConnection, ConnectionAnnotations]]:
    current = DeviceObservationCursor.objects.filter(
        computer_id=OuterRef("computer_id"),
        collector_key=OuterRef("collector_key"),
        generation_key=OuterRef("generation_key"),
        is_current=True,
    )
    return (
        DeviceConnection.objects.filter(computer_id=computer_id)
        .select_related("computer", "equipment", "interface")
        .annotate(is_current_generation=Exists(current))
        .annotate(
            freshness=Case(
                When(is_current_generation=False, then=Value("unknown")),
                When(received_at__lt=timezone.now() - timedelta(seconds=120), then=Value("stale")),
                # An old offline outbox entry is not a current physical observation.
                When(observed_at__lt=timezone.now() - timedelta(seconds=120), then=Value("stale")),
                default=Value("fresh"),
                output_field=CharField(),
            )
        )
        .order_by("collector_key", "observation_key", "pk")
    )
