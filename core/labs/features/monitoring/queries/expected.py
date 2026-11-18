"""Expected devices and whether each is present, missing or unconfirmed right now.

* ``present``: the computing unit's agent reported recently and the unit has a connected
  observation matched to the expected equipment.
* ``missing``: the agent reported recently and no connected observation matches it.
* ``unconfirmed``: no collector of the computing unit reported within the freshness window,
  so presence cannot be confirmed either way (losing the agent never proves a device left).
"""

from __future__ import annotations

from typing import TypedDict

from django.db.models import Case, CharField, Count, Exists, OuterRef, Q, QuerySet, Subquery, Value, When
from django.utils import timezone
from django_stubs_ext import WithAnnotations

from core.common.domain.errors import NotFound
from core.labs.features.equipment.public import (
    active_bench_assignments,
    equipment_ids_on_bench,
    hardware_ids_by_equipment,
)
from core.labs.models.monitoring import (
    DeviceConnection,
    DeviceConnectionState,
    DeviceObservationCursor,
    ExpectedDevice,
)

from ..contracts import DISCOVERY_COLLECTOR_KEY
from .connections import FRESHNESS_WINDOW


class ExpectedAnnotations(TypedDict):
    presence: str
    last_seen_at: object
    bench_id: int | None
    bench_name: str | None


def _annotated(queryset: QuerySet[ExpectedDevice]) -> QuerySet[WithAnnotations[ExpectedDevice, ExpectedAnnotations]]:
    cutoff = timezone.now() - FRESHNESS_WINDOW
    # Discovery snapshots are one-off evidence for linking; they never confirm presence.
    observed = DeviceConnection.objects.filter(
        computing_id=OuterRef("computing_id"), equipment_id=OuterRef("equipment_id")
    ).exclude(collector_key=DISCOVERY_COLLECTOR_KEY)
    reporting = DeviceObservationCursor.objects.filter(
        computing_id=OuterRef("computing_id"),
        is_current=True,
        last_received_at__gte=cutoff,
        last_collected_at__gte=cutoff,
    ).exclude(collector_key=DISCOVERY_COLLECTOR_KEY)
    placement = active_bench_assignments(equipment_field="computing_id")
    return (
        queryset.select_related("computing", "equipment", "creator")
        .annotate(
            is_reporting=Exists(reporting),
            is_connected=Exists(observed.filter(state=DeviceConnectionState.CONNECTED)),
            last_seen_at=Subquery(observed.order_by("-observed_at").values("observed_at")[:1]),
            bench_id=Subquery(placement.values("bench_id")[:1]),
            bench_name=Subquery(placement.values("bench__name")[:1]),
        )
        .annotate(
            presence=Case(
                When(is_reporting=False, then=Value("unconfirmed")),
                When(is_connected=True, then=Value("present")),
                default=Value("missing"),
                output_field=CharField(),
            )
        )
    )


def _scoped(*, computing_id: int | None, bench_id: int | None) -> QuerySet[ExpectedDevice]:
    queryset = ExpectedDevice.objects.filter(computing__deleted_at__isnull=True, equipment__deleted_at__isnull=True)
    if computing_id is not None:
        queryset = queryset.filter(computing_id=computing_id)
    if bench_id is not None:
        queryset = queryset.filter(computing_id__in=equipment_ids_on_bench(bench_id=bench_id))
    return queryset


def list_expected_devices(
    *, computing_id: int | None = None, bench_id: int | None = None, presence: str | None = None
) -> QuerySet[WithAnnotations[ExpectedDevice, ExpectedAnnotations]]:
    """Missing first, then unconfirmed, then present; stable within each."""
    queryset = _annotated(_scoped(computing_id=computing_id, bench_id=bench_id))
    if presence:
        queryset = queryset.filter(presence=presence)
    rank = Case(
        When(presence="missing", then=Value(0)),
        When(presence="unconfirmed", then=Value(1)),
        default=Value(2),
    )
    return queryset.annotate(presence_rank=rank).order_by("presence_rank", "computing__name", "equipment__name", "pk")


def get_expected_device(*, expected_device_id: int) -> WithAnnotations[ExpectedDevice, ExpectedAnnotations]:
    expected = _annotated(ExpectedDevice.objects.filter(pk=expected_device_id)).first()
    if expected is None:
        raise NotFound("The expected device does not exist.")
    return expected


def expected_device_counts(*, bench_id: int | None = None) -> dict[str, int]:
    return _annotated(_scoped(computing_id=None, bench_id=bench_id)).aggregate(
        missing=Count("pk", filter=Q(presence="missing")),
        unconfirmed=Count("pk", filter=Q(presence="unconfirmed")),
        present=Count("pk", filter=Q(presence="present")),
    )


MAX_WATCHED_DEVICES = 200


def expected_device_watch_list(*, computing_id: int) -> list[dict]:
    """What the computing unit's agent watches: expected equipment and its registered hardware IDs.

    Bounded to ``MAX_WATCHED_DEVICES`` units; units without a registered ID are listed with none, so
    the agent and the coordinator can both see what still needs registering.
    """
    rows = list(
        _scoped(computing_id=computing_id, bench_id=None)
        .order_by("equipment__name", "pk")
        .values_list("equipment_id", "equipment__uid", "equipment__name")[:MAX_WATCHED_DEVICES]
    )
    ids = hardware_ids_by_equipment(equipment_ids=[row[0] for row in rows], computing_id=computing_id)
    return [
        {
            "equipment_uid": uid,
            "name": name,
            "hardware_ids": [{"kind": kind, "value": value} for kind, value in ids.get(equipment_id, [])],
        }
        for equipment_id, uid, name in rows
    ]
