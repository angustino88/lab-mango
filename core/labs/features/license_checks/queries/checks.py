"""Reads for license checks: the web app's lists, and the checks an agent's computer must run."""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Count, Exists, OuterRef, Prefetch, Q, QuerySet

from core.common.domain.errors import NotFound
from core.labs.models import (
    Equipment,
    EquipmentAssignment,
    License,
    LicenseCheck,
    LicenseCheckRun,
    LicenseCheckTarget,
    LicenseObservation,
)


@dataclass(frozen=True)
class ComputerPlacement:
    """Where a computing unit is: the scopes a check target can name."""

    computing_id: int
    category_id: int | None
    bench_ids: frozenset[int]
    station_ids: frozenset[int]
    room_ids: frozenset[int]


def computer_placement(computing_id: int) -> ComputerPlacement:
    unit = Equipment.objects.filter(pk=computing_id, deleted_at__isnull=True).values("kind__category_id").first()
    if unit is None:
        raise NotFound("Computing unit not found.")
    benches, stations, rooms = set(), set(), set()
    for bench_id, bench_station, bench_room, station_id, station_room, room_id in EquipmentAssignment.objects.filter(
        equipment_id=computing_id, unassigned_at__isnull=True
    ).values_list(
        "bench_id",
        "bench__setup_location_id",
        "bench__setup_location__room_id",
        "station_id",
        "station__room_id",
        "room_id",
    ):
        benches.add(bench_id)
        stations.update((bench_station, station_id))
        rooms.update((bench_room, station_room, room_id))
    return ComputerPlacement(
        computing_id,
        unit["kind__category_id"],
        frozenset(benches - {None}),
        frozenset(stations - {None}),
        frozenset(rooms - {None}),
    )


def _targets_placement(placement: ComputerPlacement) -> Q:
    return (
        Q(equipment_id=placement.computing_id)
        | Q(bench_id__in=placement.bench_ids)
        | Q(station_id__in=placement.station_ids)
        | Q(room_id__in=placement.room_ids)
        | (Q(category_id=placement.category_id) if placement.category_id else Q(pk__in=[]))
    )


def checks_for_computer(*, computing_id: int) -> QuerySet[LicenseCheck]:
    """Enabled checks that target this computing unit (lab-wide, or by one of its scopes)."""
    placement = computer_placement(computing_id)
    targeted = LicenseCheckTarget.objects.filter(_targets_placement(placement), license_check_id=OuterRef("pk"))
    return LicenseCheck.objects.filter(Q(is_lab_wide=True) | Exists(targeted), is_enabled=True).order_by("key")


def agent_check_definitions(*, computing_id: int) -> list[dict]:
    """``GET /agent/license-checks`` items, in the shape the agent parses."""
    return [
        {
            "key": check.key,
            "revision": check.revision,
            "name": check.name,
            "vendor": check.vendor,
            "interval_minutes": check.interval_minutes,
            "probe": check.probe,
            "extract": check.extract,
            "carrier": check.carrier,
        }
        for check in checks_for_computer(computing_id=computing_id)
    ]


def _with_targets(queryset: QuerySet[LicenseCheck]) -> QuerySet[LicenseCheck]:
    targets = LicenseCheckTarget.objects.select_related("room", "station", "bench", "category", "equipment").order_by(
        "pk"
    )
    open_observations = Q(observations__removed_at__isnull=True)
    return (
        queryset.select_related("creator", "last_modified_by")
        .prefetch_related(
            Prefetch("targets", queryset=targets),
            Prefetch(
                "expected_licenses",
                queryset=License.objects.filter(deleted_at__isnull=True).order_by("name", "pk"),
                to_attr="live_expected_licenses",
            ),
            Prefetch(
                "observations",
                queryset=LicenseObservation.objects.filter(removed_at__isnull=True, license__isnull=False).only(
                    "pk", "license_check_id", "license_id"
                ),
                to_attr="live_matched_observations",
            ),
        )
        .annotate(
            license_count=Count("observations", filter=open_observations, distinct=True),
            attention_count=Count(
                "observations", filter=open_observations & ~Q(observations__status="matched"), distinct=True
            ),
        )
    )


def list_license_checks(*, q: str = "", is_enabled: bool | None = None) -> QuerySet[LicenseCheck]:
    queryset = LicenseCheck.objects.all()
    if q:
        queryset = queryset.filter(Q(name__icontains=q) | Q(key__icontains=q) | Q(vendor__icontains=q))
    if is_enabled is not None:
        queryset = queryset.filter(is_enabled=is_enabled)
    return _with_targets(queryset).order_by("name", "pk")


def get_license_check(*, check_id: int) -> LicenseCheck:
    found = _with_targets(LicenseCheck.objects.filter(pk=check_id)).first()
    if found is None:
        raise NotFound("License check not found.")
    return found


def latest_runs(*, check_id: int) -> list[LicenseCheckRun]:
    """The newest run of the check on each computer, newest first (at most 500 computers)."""
    if not LicenseCheck.objects.filter(pk=check_id).exists():
        raise NotFound("License check not found.")
    return list(
        LicenseCheckRun.objects.filter(license_check_id=check_id)
        .order_by("computing_id", "-sequence", "-pk")
        .distinct("computing_id")
        .select_related("computing")[:500]
    )


def list_license_observations(
    *,
    status: str | None = None,
    check_id: int | None = None,
    license_id: int | None = None,
    computing_id: int | None = None,
    needs_attention: bool | None = None,
    include_removed: bool = False,
    q: str = "",
) -> QuerySet[LicenseObservation]:
    queryset = LicenseObservation.objects.select_related(
        "license_check", "computing", "carrier_equipment", "license", "license__vendor", "last_run"
    )
    if not include_removed:
        queryset = queryset.filter(removed_at__isnull=True)
    if status:
        queryset = queryset.filter(status=status)
    if needs_attention is True:
        queryset = queryset.exclude(status="matched")
    elif needs_attention is False:
        queryset = queryset.filter(status="matched")
    if check_id is not None:
        queryset = queryset.filter(license_check_id=check_id)
    if license_id is not None:
        queryset = queryset.filter(license_id=license_id)
    if computing_id is not None:
        queryset = queryset.filter(computing_id=computing_id)
    if q:
        queryset = queryset.filter(
            Q(product_name__icontains=q)
            | Q(license_serial__icontains=q)
            | Q(carrier_hardware_value__icontains=q)
            | Q(computing__name__icontains=q)
            | Q(computing__sku__icontains=q)
        )
    return queryset.order_by("computing__name", "product_name", "pk")
