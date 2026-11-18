"""Paginated, joined connection projection. Freshness never uses heartbeat time.

A row is ``fresh`` when its collector's cursor is current for the row's generation and the
cursor's last applied batch was both collected and received within the freshness window.
Applied incremental batches are contiguous, so the latest batch confirms devices it did
not mention; an empty incremental batch is therefore a valid keep-alive.

A row ``needs_attention`` when it is not matched to exactly one inventory unit, or when it
was last reported connected but that report is no longer fresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypedDict

from django.db.models import (
    BooleanField,
    Case,
    CharField,
    Count,
    Exists,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
    When,
)
from django.utils import timezone
from django_stubs_ext import WithAnnotations

from core.common.domain.errors import NotFound
from core.labs.features.equipment.public import active_bench_assignments, equipment_ids_on_bench
from core.labs.models.monitoring import (
    DeviceConnection,
    DeviceConnectionState,
    DeviceMatchStatus,
    DeviceObservationCursor,
    ExpectedDevice,
    MonitoringEvent,
    MonitoringEventAction,
)

from ..contracts import DISCOVERY_COLLECTOR_KEY

FRESHNESS_WINDOW = timedelta(seconds=120)
HISTORY_SCAN_LIMIT = 200
HISTORY_LIMIT = 20


class ConnectionAnnotations(TypedDict):
    is_current_generation: bool
    freshness: str
    needs_attention: bool
    bench_id: int | None
    bench_name: str | None
    expected_device_id: int | None
    state_rank: int


def _annotated(
    queryset: QuerySet[DeviceConnection],
) -> QuerySet[WithAnnotations[DeviceConnection, ConnectionAnnotations]]:
    current = DeviceObservationCursor.objects.filter(
        computing_id=OuterRef("computing_id"),
        collector_key=OuterRef("collector_key"),
        generation_key=OuterRef("generation_key"),
        is_current=True,
    )
    placement = active_bench_assignments(equipment_field="computing_id")
    expectation = ExpectedDevice.objects.filter(
        computing_id=OuterRef("computing_id"), equipment_id=OuterRef("equipment_id")
    )
    cutoff = timezone.now() - FRESHNESS_WINDOW
    return (
        queryset.select_related("computing", "equipment", "interface")
        .annotate(
            is_current_generation=Exists(current),
            confirmed_received_at=Subquery(current.values("last_received_at")[:1]),
            confirmed_collected_at=Subquery(current.values("last_collected_at")[:1]),
            bench_id=Subquery(placement.values("bench_id")[:1]),
            bench_name=Subquery(placement.values("bench__name")[:1]),
            expected_device_id=Subquery(expectation.values("pk")[:1]),
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
        .annotate(
            needs_attention=Case(
                When(~Q(match_status=DeviceMatchStatus.MATCHED), then=Value(True)),
                When(Q(state=DeviceConnectionState.CONNECTED) & ~Q(freshness="fresh"), then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ),
        )
    )


def list_device_connections(
    *,
    computing_id: int | None = None,
    bench_id: int | None = None,
    state: str | None = None,
    attention: bool | None = None,
    search: str | None = None,
) -> QuerySet[WithAnnotations[DeviceConnection, ConnectionAnnotations]]:
    """Grouped by computing unit, connected devices first, then most recently observed."""
    queryset = DeviceConnection.objects.all()
    if computing_id is not None:
        queryset = queryset.filter(computing_id=computing_id)
    if bench_id is not None:
        queryset = queryset.filter(computing_id__in=equipment_ids_on_bench(bench_id=bench_id))
    if state:
        queryset = queryset.filter(state=state)
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(serial_number__icontains=search)
            | Q(hardware_ids__icontains=search)
            | Q(equipment__name__icontains=search)
            | Q(equipment__sku__icontains=search)
            | Q(computing__name__icontains=search)
            | Q(computing__sku__icontains=search)
        )
    annotated = _annotated(queryset)
    if attention is not None:
        annotated = annotated.filter(needs_attention=attention)
    return annotated.order_by(
        "computing__name", "computing_id", "state_rank", "-observed_at", "collector_key", "observation_key", "pk"
    )


def get_device_connection(*, connection_id: int) -> WithAnnotations[DeviceConnection, ConnectionAnnotations]:
    connection = _annotated(DeviceConnection.objects.filter(pk=connection_id)).first()
    if connection is None:
        raise NotFound("The device connection does not exist.")
    return connection


@dataclass(frozen=True, slots=True)
class DeviceConnectionSummary:
    connected: int
    needs_matching: int
    unconfirmed: int
    missing: int
    computing_units: int


def device_connection_summary(*, bench_id: int | None = None) -> DeviceConnectionSummary:
    """Lab-wide counts in two aggregate queries (connections, then expectations)."""
    from .expected import expected_device_counts

    queryset = DeviceConnection.objects.all()
    if bench_id is not None:
        queryset = queryset.filter(computing_id__in=equipment_ids_on_bench(bench_id=bench_id))
    connected = Q(state=DeviceConnectionState.CONNECTED)
    totals = _annotated(queryset).aggregate(
        connected=Count("pk", filter=connected & Q(freshness="fresh")),
        needs_matching=Count("pk", filter=~Q(match_status=DeviceMatchStatus.MATCHED)),
        unconfirmed=Count("pk", filter=connected & ~Q(freshness="fresh")),
        computing_units=Count("computing_id", distinct=True),
    )
    return DeviceConnectionSummary(missing=expected_device_counts(bench_id=bench_id)["missing"], **totals)


@dataclass(frozen=True, slots=True)
class DeviceConnectionChange:
    state: str
    observed_at: datetime
    sequence: int
    is_complete: bool


def device_connection_history(connection: DeviceConnection) -> list[DeviceConnectionChange]:
    """State changes of one device instance, newest first, from its collector's snapshots.

    Reads at most the latest ``HISTORY_SCAN_LIMIT`` inventory snapshots of the collector.
    A complete snapshot that omits the device records it disconnected; an incremental
    batch that omits it changes nothing.
    """
    snapshots = list(
        MonitoringEvent.objects.filter(
            computer_id=connection.computing_id,
            action=MonitoringEventAction.INVENTORY_SNAPSHOT,
            subject_id=connection.collector_key,
        )
        .order_by("-occurred_at", "-pk")
        .values_list("occurred_at", "payload")[:HISTORY_SCAN_LIMIT]
    )
    changes: list[DeviceConnectionChange] = []
    previous: str | None = None
    for occurred_at, payload in reversed(snapshots):
        if not isinstance(payload, dict):
            continue
        devices = payload.get("devices") or []
        reported = next(
            (
                device
                for device in devices
                if isinstance(device, dict) and device.get("observation_key") == connection.observation_key
            ),
            None,
        )
        if reported is not None:
            state = str(reported.get("state", ""))
        elif payload.get("is_complete") and previous is not None:
            state = DeviceConnectionState.DISCONNECTED
        else:
            continue
        if state != previous:
            changes.append(
                DeviceConnectionChange(
                    state=state,
                    observed_at=occurred_at,
                    sequence=int(payload.get("sequence") or 0),
                    is_complete=bool(payload.get("is_complete")),
                )
            )
            previous = state
    return list(reversed(changes))[:HISTORY_LIMIT]


def connected_equipment_ids(*, computing_id: int) -> set[int]:
    """Units the computing unit's own agent reports connected right now (fresh, matched, not discovery).

    Used by license checks to confirm a license carrier (for example a CANcase) is at this computer.
    """
    cutoff = timezone.now() - FRESHNESS_WINDOW
    return set(
        DeviceConnection.objects.filter(
            computing_id=computing_id,
            state=DeviceConnectionState.CONNECTED,
            equipment__isnull=False,
            received_at__gte=cutoff,
        )
        .exclude(collector_key=DISCOVERY_COLLECTOR_KEY)
        .values_list("equipment_id", flat=True)
    )
