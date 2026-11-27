"""Which benches are free in a time window, and when the others are busy.

Six queries whatever the number of benches: candidates, their computers, overlapping bookings, overlapping
downtime of benches, of stations and of rooms, plus the caller's favorites. Other people's bookings are reported
only as busy time: no holder, code or reason leaves this module.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from django.db.models import Exists, OuterRef, Q

from core.labs.features.bench_bookings.queries.bench_bookings import may_book_during_downtime
from core.labs.models import (
    Bench,
    BenchBooking,
    BenchFavorite,
    Booking,
    EquipmentAssignment,
    ResourceDowntime,
    ResourceLifecycleStatus,
    Room,
    Station,
)

MAX_WINDOW = timedelta(days=14)
MAX_RESULTS = 20
MAX_CANDIDATES = 500
BUSY_BOOKING = "booking"
BUSY_DOWNTIME = "downtime"


@dataclass(frozen=True, slots=True)
class Period:
    starts_at: datetime
    ends_at: datetime

    @property
    def duration(self) -> timedelta:
        return self.ends_at - self.starts_at


@dataclass(frozen=True, slots=True)
class BusyPeriod:
    starts_at: datetime
    ends_at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class ResourceRef:
    id: int
    uid: Any
    name: str


@dataclass(frozen=True, slots=True)
class NamedRef:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class BenchAvailability:
    bench: ResourceRef
    station: ResourceRef | None
    room: ResourceRef | None
    type: NamedRef | None
    has_computing: bool
    is_fully_free: bool
    is_favorite: bool
    free_periods: list[Period] = field(default_factory=list)
    busy_periods: list[BusyPeriod] = field(default_factory=list)

    @property
    def next_free_at(self) -> datetime | None:
        """Start of the first free period, or ``None`` when the bench is busy for the whole window."""
        return self.free_periods[0].starts_at if self.free_periods else None

    @property
    def longest_free(self) -> timedelta:
        return max((period.duration for period in self.free_periods), default=timedelta(0))


@dataclass(frozen=True, slots=True)
class AvailabilityResult:
    window_starts_at: datetime
    window_ends_at: datetime
    benches: list[BenchAvailability]
    is_truncated: bool


def find_bench_availability(
    *,
    actor: Any,
    starts_at: datetime,
    ends_at: datetime,
    lab_operator: bool,
    bench_ids: Sequence[int] = (),
    type_ids: Sequence[int] = (),
    bench_group_ids: Sequence[int] = (),
    setup_location_ids: Sequence[int] = (),
    has_computing: bool | None = None,
    q: str | None = None,
    min_free_minutes: int | None = None,
    only_fully_free: bool = True,
    exclude_bench_ids: Iterable[int] = (),
    exclude_booking_id: int | None = None,
    limit: int = 10,
) -> AvailabilityResult:
    """Rank in-service benches by how free they are in ``[starts_at, ends_at)``.

    ``only_fully_free`` keeps benches with no busy time; otherwise a bench qualifies with any free period of at
    least ``min_free_minutes`` (default: any). ``lab_operator`` says whether downtime open to lab operators counts
    as free (``bench_booking.book_during_downtime``). Order: fully free, favorites, longest free period, name.
    """
    candidates = list(
        _candidates(
            bench_ids=bench_ids,
            type_ids=type_ids,
            bench_group_ids=bench_group_ids,
            setup_location_ids=setup_location_ids,
            has_computing=has_computing,
            q=q,
            exclude_bench_ids=exclude_bench_ids,
        )[: MAX_CANDIDATES + 1]
    )
    is_truncated = len(candidates) > MAX_CANDIDATES
    candidates = candidates[:MAX_CANDIDATES]
    ids = [row["id"] for row in candidates]
    window = Period(starts_at, ends_at)
    busy = _busy_periods(
        candidates=candidates, window=window, lab_operator=lab_operator, exclude_booking_id=exclude_booking_id
    )
    computing = _benches_with_computing(ids)
    favorites = _favorites(actor=actor, bench_ids=ids)
    min_free = timedelta(minutes=min_free_minutes or 0)

    results = []
    for row in candidates:
        busy_periods = _merge(busy.get(row["id"], []))
        free_periods = _free_periods(window, busy_periods)
        item = BenchAvailability(
            bench=ResourceRef(row["id"], row["uid"], row["name"] or row["sku"]),
            station=_ref(row, "setup_location"),
            room=_ref(row, "setup_location__room"),
            type=NamedRef(row["type_id"], row["type__name"]) if row["type_id"] else None,
            has_computing=row["id"] in computing,
            is_fully_free=not busy_periods,
            is_favorite=row["id"] in favorites,
            free_periods=free_periods,
            busy_periods=busy_periods,
        )
        if only_fully_free and not item.is_fully_free:
            continue
        if not only_fully_free and (not free_periods or item.longest_free < min_free):
            continue
        results.append(item)
    results.sort(key=lambda item: (not item.is_fully_free, not item.is_favorite, -item.longest_free, item.bench.name))
    is_truncated = is_truncated or len(results) > limit
    return AvailabilityResult(starts_at, ends_at, results[:limit], is_truncated)


def _candidates(*, bench_ids, type_ids, bench_group_ids, setup_location_ids, has_computing, q, exclude_bench_ids):
    queryset = Bench.objects.filter(deleted_at__isnull=True, lifecycle_status=ResourceLifecycleStatus.IN_SERVICE)
    # A bench whose station or room is not in service does not accept bookings (design rule 3).
    queryset = queryset.filter(
        Q(setup_location__isnull=True) | Q(setup_location__lifecycle_status=ResourceLifecycleStatus.IN_SERVICE)
    ).filter(
        Q(setup_location__room__isnull=True)
        | Q(setup_location__room__lifecycle_status=ResourceLifecycleStatus.IN_SERVICE)
    )
    if bench_ids:
        queryset = queryset.filter(pk__in=bench_ids)
    if type_ids:
        queryset = queryset.filter(type_id__in=type_ids)
    if bench_group_ids:
        queryset = queryset.filter(bench_group_id__in=bench_group_ids)
    if setup_location_ids:
        queryset = queryset.filter(setup_location_id__in=setup_location_ids)
    if q:
        queryset = queryset.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    if has_computing is not None:
        computer = Exists(_computing_assignments().filter(bench_id=OuterRef("pk")))
        queryset = queryset.filter(computer if has_computing else ~computer)
    if exclude_bench_ids:
        queryset = queryset.exclude(pk__in=list(exclude_bench_ids))
    return queryset.order_by("name", "pk").values(
        "id",
        "uid",
        "sku",
        "name",
        "type_id",
        "type__name",
        "setup_location_id",
        "setup_location__uid",
        "setup_location__name",
        "setup_location__sku",
        "setup_location__room_id",
        "setup_location__room__uid",
        "setup_location__room__name",
        "setup_location__room__sku",
    )


def _computing_assignments():
    """Same rule as ``bench_has_computing``: a monitored-category unit placed on the bench now."""
    return EquipmentAssignment.objects.filter(
        unassigned_at__isnull=True,
        equipment__deleted_at__isnull=True,
        equipment__kind__category__monitored=True,
    )


def _benches_with_computing(bench_ids: list[int]) -> set[int]:
    if not bench_ids:
        return set()
    return set(_computing_assignments().filter(bench_id__in=bench_ids).values_list("bench_id", flat=True))


def _favorites(*, actor: Any, bench_ids: list[int]) -> set[int]:
    if not bench_ids or not getattr(actor, "is_authenticated", False):
        return set()
    return set(
        BenchFavorite.objects.filter(user_id=actor.pk, bench_id__in=bench_ids).values_list("bench_id", flat=True)
    )


def _busy_periods(
    *, candidates, window: Period, lab_operator: bool, exclude_booking_id: int | None = None
) -> dict[int, list[BusyPeriod]]:
    busy: dict[int, list[BusyPeriod]] = defaultdict(list)
    ids = [row["id"] for row in candidates]
    if not ids:
        return busy
    bookings = BenchBooking.objects.filter(
        bench_id__in=ids,
        status__in=Booking.ACTIVE_STATUSES,
        approval_status__in=Booking.RESERVING_APPROVAL_STATUSES,
        starts_at__lt=window.ends_at,
        ends_at__gt=window.starts_at,
    )
    if exclude_booking_id is not None:
        bookings = bookings.exclude(pk=exclude_booking_id)
    bookings = bookings.values_list("bench_id", "starts_at", "ends_at")
    for bench_id, starts_at, ends_at in bookings:
        busy[bench_id].append(_clip(starts_at, ends_at, window, BUSY_BOOKING))

    benches_by_station: dict[int, list[int]] = defaultdict(list)
    benches_by_room: dict[int, list[int]] = defaultdict(list)
    for row in candidates:
        if row["setup_location_id"] is not None:
            benches_by_station[row["setup_location_id"]].append(row["id"])
        if row["setup_location__room_id"] is not None:
            benches_by_room[row["setup_location__room_id"]].append(row["id"])
    for model, owners in (
        (Bench, {bench_id: [bench_id] for bench_id in ids}),
        (Station, benches_by_station),
        (Room, benches_by_room),
    ):
        if not owners:
            continue
        windows = (
            ResourceDowntime.objects.for_resources(model, owners.keys())
            .overlapping(window.starts_at, window.ends_at)
            .blocking(lab_operator=lab_operator)
            .values_list("resource_object_id", "starts_at", "ends_at")
        )
        for object_id, starts_at, ends_at in windows:
            for bench_id in owners.get(int(object_id), ()):
                busy[bench_id].append(_clip(starts_at, ends_at or window.ends_at, window, BUSY_DOWNTIME))
    return busy


def _clip(starts_at: datetime, ends_at: datetime, window: Period, reason: str) -> BusyPeriod:
    return BusyPeriod(max(starts_at, window.starts_at), min(ends_at, window.ends_at), reason)


def _merge(periods: list[BusyPeriod]) -> list[BusyPeriod]:
    """Sort and join overlapping or touching busy periods; a downtime wins the reason of a merged block."""
    merged: list[BusyPeriod] = []
    for period in sorted(periods, key=lambda item: (item.starts_at, item.ends_at)):
        if merged and period.starts_at <= merged[-1].ends_at:
            last = merged[-1]
            reason = BUSY_DOWNTIME if BUSY_DOWNTIME in (last.reason, period.reason) else last.reason
            merged[-1] = BusyPeriod(last.starts_at, max(last.ends_at, period.ends_at), reason)
        else:
            merged.append(period)
    return merged


def _free_periods(window: Period, busy: list[BusyPeriod]) -> list[Period]:
    free: list[Period] = []
    cursor = window.starts_at
    for period in busy:
        if period.starts_at > cursor:
            free.append(Period(cursor, period.starts_at))
        cursor = max(cursor, period.ends_at)
    if cursor < window.ends_at:
        free.append(Period(cursor, window.ends_at))
    return free


def _ref(row: dict[str, Any], prefix: str) -> ResourceRef | None:
    if row[f"{prefix}_id"] is None:
        return None
    return ResourceRef(row[f"{prefix}_id"], row[f"{prefix}__uid"], row[f"{prefix}__name"] or row[f"{prefix}__sku"])


def list_bench_availability(
    *, actor: Any, starts_at: datetime, ends_at: datetime, **filters: Any
) -> AvailabilityResult:
    """``find_bench_availability`` for ``actor``: downtime open to lab operators is free only for them."""
    return find_bench_availability(
        actor=actor, starts_at=starts_at, ends_at=ends_at, lab_operator=may_book_during_downtime(actor), **filters
    )
