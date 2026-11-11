"""Read-only query selectors for the laboratory dashboard feature."""

from __future__ import annotations

from typing import Any

from django.db.models import (
    BooleanField,
    Count,
    Exists,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Value,
)
from django.utils import timezone

from core.labs.models import (
    Bench,
    BenchBooking,
    BenchFavorite,
    BookingStatus,
    ComputingActivity,
    ComputingActivityStatus,
    LicenseAssignment,
)
from core.labs.models.resource.equipment.assignment import EquipmentAssignment

from ..exceptions import DashboardResourceNotFound


def list_dashboard_benches(
    actor: Any = None,
    *,
    search: str | None = None,
    bench_group: int | None = None,
    lifecycle_status: str | None = None,
    activity_status: str | None = None,
    is_booked: bool | None = None,
    is_favorite: bool | None = None,
    location: int | None = None,
    has_computing: bool | None = None,
    is_mapped: bool | None = None,
) -> QuerySet[Bench]:
    """Retrieve an optimized queryset of active benches for the dashboard view.

    Prefetches active bookings and computing equipment/activity states to eliminate
    N+1 database roundtrips during serialization.
    """
    now = timezone.now()

    active_bookings_prefetch = Prefetch(
        "bookings",
        queryset=BenchBooking.objects.filter(
            starts_at__lte=now,
            ends_at__gte=now,
            status__in=[BookingStatus.RESERVED, BookingStatus.IN_PROGRESS],
        ).select_related("creator"),
        to_attr="_active_bookings",
    )

    active_assignments_prefetch = Prefetch(
        "equipment_assignments",
        queryset=EquipmentAssignment.objects.filter(
            unassigned_at__isnull=True,
            equipment__deleted_at__isnull=True,
        ).select_related(
            "equipment",
            "equipment__kind__category",
            "equipment__computing_profile",
            "equipment__activity",
        ).prefetch_related(
            Prefetch(
                "equipment__license_assignments",
                queryset=LicenseAssignment.objects.filter(
                    unassigned_at__isnull=True,
                    license__deleted_at__isnull=True,
                ).select_related("license"),
                to_attr="_active_license_assignments",
            )
        ).order_by("position", "pk"),
        to_attr="_active_equipment_assignments",
    )

    queryset = (
        Bench.objects.filter(deleted_at__isnull=True)
        .select_related(
            "type",
            "bench_group",
            "owner",
            "station_slot",
            "setup_location",
            "setup_location__room__building",
            "setup_location__room__city",
            "setup_location__room__country",
        )
        .prefetch_related(active_bookings_prefetch, active_assignments_prefetch)
    )

    if actor is not None and getattr(actor, "is_authenticated", False):
        queryset = queryset.annotate(
            is_favorite=Exists(BenchFavorite.objects.filter(user=actor, bench_id=OuterRef("pk")))
        )
    else:
        queryset = queryset.annotate(is_favorite=Value(False, output_field=BooleanField()))

    queryset = queryset.annotate(
        equipment_count=Count(
            "equipment_assignments",
            filter=Q(
                equipment_assignments__unassigned_at__isnull=True,
                equipment_assignments__equipment__deleted_at__isnull=True,
            ),
            distinct=True,
        )
    )

    has_joins_for_filter = False

    if bench_group is not None:
        queryset = queryset.filter(bench_group_id=bench_group)

    if lifecycle_status is not None:
        queryset = queryset.filter(lifecycle_status=lifecycle_status)

    if location is not None:
        queryset = queryset.filter(
            Q(setup_location_id=location) | Q(setup_location__room_id=location)
        )

    if is_favorite is not None:
        if actor is not None and getattr(actor, "is_authenticated", False):
            bookmarks = BenchFavorite.objects.filter(user=actor, bench_id=OuterRef("pk"))
            queryset = queryset.filter(Exists(bookmarks) if is_favorite else ~Exists(bookmarks))
        elif is_favorite:
            return queryset.none()

    if is_booked is not None:
        active_booking_subquery = BenchBooking.objects.filter(
            bench_id=OuterRef("pk"),
            starts_at__lte=now,
            ends_at__gte=now,
            status__in=[BookingStatus.RESERVED, BookingStatus.IN_PROGRESS],
        )
        queryset = queryset.filter(
            Exists(active_booking_subquery) if is_booked else ~Exists(active_booking_subquery)
        )

    if has_computing is not None:
        computing_subquery = EquipmentAssignment.objects.filter(
            bench_id=OuterRef("pk"),
            unassigned_at__isnull=True,
            equipment__deleted_at__isnull=True,
            equipment__computing_profile__isnull=False,
        )
        queryset = queryset.filter(
            Exists(computing_subquery) if has_computing else ~Exists(computing_subquery)
        )

    if is_mapped is not None:
        mapping_condition = (
            Q(setup_location__isnull=False, setup_location__deleted_at__isnull=True)
            | Q(station_slot__isnull=False)
        )
        queryset = queryset.filter(mapping_condition if is_mapped else ~mapping_condition)

    if activity_status is not None:
        has_joins_for_filter = True
        queryset = queryset.filter(
            equipment_assignments__unassigned_at__isnull=True,
            equipment_assignments__equipment__activity__status=activity_status,
        )

    if search:
        has_joins_for_filter = True
        search_term = search.strip()
        queryset = queryset.filter(
            Q(name__icontains=search_term)
            | Q(sku__icontains=search_term)
            | Q(description__icontains=search_term)
            | Q(bench_group__name__icontains=search_term)
            | Q(setup_location__name__icontains=search_term)
            | Q(setup_location__room__name__icontains=search_term)
            | Q(
                equipment_assignments__equipment__computing_profile__ip_address__icontains=search_term,
                equipment_assignments__unassigned_at__isnull=True,
            )
            | Q(
                equipment_assignments__equipment__activity__remote_user__icontains=search_term,
                equipment_assignments__unassigned_at__isnull=True,
            )
        )

    if has_joins_for_filter:
        queryset = queryset.distinct()

    return queryset.order_by("name", "id")


def get_dashboard_summary(actor: Any = None) -> dict[str, Any]:
    """Calculate aggregate dashboard statistics across benches and computing assets."""
    now = timezone.now()

    total_benches = Bench.objects.filter(deleted_at__isnull=True).count()

    active_bookings_count = BenchBooking.objects.filter(
        starts_at__lte=now,
        ends_at__gte=now,
        status__in=[BookingStatus.RESERVED, BookingStatus.IN_PROGRESS],
        bench__deleted_at__isnull=True,
    ).count()

    favorited_benches_count = 0
    if actor is not None and getattr(actor, "is_authenticated", False):
        favorited_benches_count = BenchFavorite.objects.filter(
            user=actor,
            bench__deleted_at__isnull=True,
        ).count()

    lifecycle_distribution: dict[str, int] = {
        choice[0]: 0 for choice in Bench.LIFECYCLE_STATUSES
    }
    lifecycle_rows = (
        Bench.objects.filter(deleted_at__isnull=True)
        .values("lifecycle_status")
        .annotate(total=Count("id"))
    )
    for row in lifecycle_rows:
        status_key = row["lifecycle_status"]
        if status_key in lifecycle_distribution:
            lifecycle_distribution[status_key] = row["total"]

    activity_distribution: dict[str, int] = {
        choice[0]: 0 for choice in ComputingActivityStatus.choices
    }
    activity_rows = (
        ComputingActivity.objects.filter(
            computing__bench_assignments__unassigned_at__isnull=True,
            computing__bench_assignments__bench__isnull=False,
            computing__bench_assignments__bench__deleted_at__isnull=True,
        )
        .values("status")
        .annotate(total=Count("id"))
    )
    for row in activity_rows:
        activity_key = row["status"]
        if activity_key in activity_distribution:
            activity_distribution[activity_key] = row["total"]

    utilization_rate = (
        round((active_bookings_count / total_benches) * 100.0, 2)
        if total_benches > 0
        else 0.0
    )

    return {
        "total_benches": total_benches,
        "active_bookings_count": active_bookings_count,
        "favorited_benches_count": favorited_benches_count,
        "lifecycle_distribution": lifecycle_distribution,
        "activity_distribution": activity_distribution,
        "utilization_rate": utilization_rate,
    }


def get_dashboard_bench_detail(bench_id: int, actor: Any = None) -> Bench:
    """Retrieve detailed operational state for a single bench."""
    now = timezone.now()

    active_bookings_prefetch = Prefetch(
        "bookings",
        queryset=BenchBooking.objects.filter(
            starts_at__lte=now,
            ends_at__gte=now,
            status__in=[BookingStatus.RESERVED, BookingStatus.IN_PROGRESS],
        ).select_related("creator"),
        to_attr="_active_bookings",
    )

    upcoming_bookings_prefetch = Prefetch(
        "bookings",
        queryset=BenchBooking.objects.filter(
            ends_at__gte=now,
            status__in=[BookingStatus.RESERVED, BookingStatus.IN_PROGRESS],
        ).select_related("creator").order_by("starts_at")[:10],
        to_attr="_upcoming_bookings",
    )

    active_assignments_prefetch = Prefetch(
        "equipment_assignments",
        queryset=EquipmentAssignment.objects.filter(
            unassigned_at__isnull=True,
            equipment__deleted_at__isnull=True,
        ).select_related(
            "equipment",
            "equipment__kind__category",
            "equipment__kind",
            "equipment__type",
            "equipment__computing_profile",
            "equipment__activity",
        ).prefetch_related(
            Prefetch(
                "equipment__license_assignments",
                queryset=LicenseAssignment.objects.filter(
                    unassigned_at__isnull=True,
                    license__deleted_at__isnull=True,
                ).select_related("license"),
                to_attr="_active_license_assignments",
            )
        ).order_by("position", "pk"),
        to_attr="_active_equipment_assignments",
    )

    queryset = (
        Bench.objects.filter(pk=bench_id, deleted_at__isnull=True)
        .select_related(
            "type",
            "bench_group",
            "owner",
            "station_slot",
            "setup_location",
            "setup_location__room__building",
            "setup_location__room__city",
            "setup_location__room__country",
        )
        .prefetch_related(
            active_bookings_prefetch,
            upcoming_bookings_prefetch,
            active_assignments_prefetch,
        )
    )

    if actor is not None and getattr(actor, "is_authenticated", False):
        queryset = queryset.annotate(
            is_favorite=Exists(BenchFavorite.objects.filter(user=actor, bench_id=OuterRef("pk")))
        )
    else:
        queryset = queryset.annotate(is_favorite=Value(False, output_field=BooleanField()))

    bench = queryset.first()
    if bench is None:
        raise DashboardResourceNotFound(f"Bench with ID {bench_id} does not exist.")

    return bench


__all__ = (
    "get_dashboard_bench_detail",
    "get_dashboard_summary",
    "list_dashboard_benches",
)
