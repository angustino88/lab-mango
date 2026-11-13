"""Read-only bench booking selectors and overlap projections."""

from datetime import datetime
from typing import Any

from django.db.models import Q, QuerySet

from core.labs.features.bench_bookings.contracts import SessionBookingFacts
from core.labs.models import (
    BenchBooking,
    Booking,
    BookingApprovalStatus,
    BookingStatus,
    LabProject,
    ResourceDowntime,
    ResourceLifecycleStatus,
    Room,
    Station,
)
from core.users.public import LabsRole, has_labs_role


def list_bench_bookings(
    *,
    actor: Any,
    view_side: str | None = None,
    creator: str | None = None,
    creator_id: int | None = None,
    bench_id: int | None = None,
    project_id: int | None = None,
    status: str | None = None,
    approval_status: str | None = None,
    booking_code: str | None = None,
    starts_at_after: datetime | None = None,
    starts_at_before: datetime | None = None,
    ordering: list[str] | None = None,
    q: str | None = None,
    search: str | None = None,
) -> QuerySet[BenchBooking]:
    """Coordinators see the schedule; everyone else sees only bookings they created.

    The explicit my_booking filter narrows elevated users to their own records.
    API keys and actors without a real authenticated user have no personal scope.
    """
    bookings = BenchBooking.objects.select_related("bench", "project", "creator")
    if ordering is None:
        bookings = bookings.order_by("-starts_at", "-pk")
    else:
        ordering_fields = {
            "starts_at": "starts_at",
            "ends_at": "ends_at",
            "created_at": "created",
            "id": "pk",
        }
        ordering_paths = []
        seen_fields = set()
        for field in ordering:
            descending = field.startswith("-")
            public_field = field[1:] if descending else field
            if public_field not in ordering_fields or public_field in seen_fields:
                raise ValueError("Unsupported bench booking ordering.")
            seen_fields.add(public_field)
            ordering_paths.append(f"{'-' if descending else ''}{ordering_fields[public_field]}")
        if not any(path.lstrip("-") == "pk" for path in ordering_paths):
            ordering_paths.append("pk")
        bookings = bookings.order_by(*ordering_paths)
    bookings = visible_to(bookings, actor=actor)
    if view_side == "my_booking" and getattr(actor, "is_authenticated", False):
        bookings = bookings.filter(creator_id=actor.pk)

    if creator_id is not None:
        bookings = bookings.filter(creator_id=creator_id)
    elif creator:
        if str(creator).isdigit():
            bookings = bookings.filter(creator_id=int(creator))
        else:
            bookings = bookings.filter(creator__username__iexact=creator)

    if bench_id is not None:
        bookings = bookings.filter(bench_id=bench_id)
    if project_id is not None:
        bookings = bookings.filter(project_id=project_id)
    if status:
        bookings = bookings.filter(status__iexact=status)
    if approval_status:
        bookings = bookings.filter(approval_status__iexact=approval_status)
    if booking_code:
        bookings = bookings.filter(booking_code__iexact=booking_code)
    if starts_at_after is not None:
        bookings = bookings.filter(ends_at__gt=starts_at_after)
    if starts_at_before is not None:
        bookings = bookings.filter(starts_at__lt=starts_at_before)

    search_term = q or search
    if search_term:
        bookings = bookings.filter(
            Q(booking_code__icontains=search_term)
            | Q(bench__name__icontains=search_term)
            | Q(bench__sku__icontains=search_term)
        )

    return bookings


def visible_to(bookings: QuerySet[BenchBooking], *, actor: Any) -> QuerySet[BenchBooking]:
    """Object scope for booking reads: coordinators/admins see all, users only what they created.

    Callers without a user (anonymous or API-key-only) see nothing.
    """
    if not getattr(actor, "is_authenticated", False):
        return bookings.none()
    if has_labs_role(actor, LabsRole.COORDINATOR):
        return bookings
    return bookings.filter(creator_id=actor.pk)


def get_visible_bench_booking(*, actor: Any, booking_id: int) -> BenchBooking:
    """Booking detail for ``actor``; raises DoesNotExist (404) outside the actor's scope."""
    return visible_to(_booking_detail_queryset(), actor=actor).get(pk=booking_id)


def get_visible_bench_booking_by_code(*, actor: Any, booking_code: str) -> BenchBooking:
    """Booking detail by code for ``actor``; raises DoesNotExist (404) outside the actor's scope."""
    return visible_to(_booking_detail_queryset(), actor=actor).get(booking_code=booking_code)


def _booking_detail_queryset() -> QuerySet[BenchBooking]:
    return BenchBooking.objects.select_related("bench", "project", "creator", "approved_by")


def get_bench_booking(*, booking_id):
    return BenchBooking.objects.select_related("bench", "project", "creator", "approved_by").get(pk=booking_id)


def get_bench_booking_by_code(*, booking_code: str):
    return BenchBooking.objects.select_related("bench", "project", "creator", "approved_by").get(
        booking_code=booking_code
    )


def find_bench_booking_for_agent_login(*, booking_code: str) -> BenchBooking | None:
    """The booking with this code and the users it names, or None. One query."""
    return BenchBooking.objects.select_related("requester", "creator").filter(booking_code=booking_code).first()


def find_session_booking_facts(*, booking_code: str) -> SessionBookingFacts | None:
    """Facts of the booking with this code, or None. One query."""
    row = (
        BenchBooking.objects.filter(booking_code=booking_code)
        .values("pk", "bench_id", "starts_at", "ends_at", "status", "approval_status")
        .first()
    )
    if row is None:
        return None
    return SessionBookingFacts(
        booking_id=row["pk"],
        bench_id=row["bench_id"],
        starts_at=row["starts_at"],
        ends_at=row["ends_at"],
        status=row["status"],
        approval_status=row["approval_status"],
    )


def conflicting_bench_bookings(*, bench_id, starts_at, ends_at, exclude_id=None):
    """Return reserving bookings that overlap the requested half-open period."""
    queryset = BenchBooking.objects.filter(
        bench_id=bench_id,
        status__in=Booking.ACTIVE_STATUSES,
        approval_status__in=Booking.RESERVING_APPROVAL_STATUSES,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    )
    if exclude_id is not None:
        queryset = queryset.exclude(pk=exclude_id)
    return queryset


def bench_parent_blocker(*, bench) -> str | None:
    """Why the bench's station or room does not accept bookings (not in service), or ``None``.

    Design rule 3. One query; the caller holds the bench lock.
    """
    if bench.setup_location_id is None:
        return None
    row = (
        Station.objects.filter(pk=bench.setup_location_id)
        .values("lifecycle_status", "name", "sku", "room__lifecycle_status", "room__name", "room__sku")
        .first()
    )
    if row is None:
        return None
    if row["lifecycle_status"] != ResourceLifecycleStatus.IN_SERVICE:
        return f"Station {row['name'] or row['sku']} is {row['lifecycle_status']}."
    if row["room__lifecycle_status"] not in (None, ResourceLifecycleStatus.IN_SERVICE):
        return f"Room {row['room__name'] or row['room__sku']} is {row['room__lifecycle_status']}."
    return None


def bench_downtime_blocker(*, bench, starts_at, ends_at) -> str | None:
    """The first downtime window of the bench, its station or its room that overlaps the period.

    Design rule 3. Downtime writers lock the bench row this caller already holds (``lock_benches``), so a
    window created concurrently is either committed and seen here, or waits for this transaction.
    """
    scopes = [(type(bench), bench.pk, "Bench")]
    if bench.setup_location_id is not None:
        scopes.append((Station, bench.setup_location_id, "Station"))
        room_id = Station.objects.filter(pk=bench.setup_location_id).values_list("room_id", flat=True).first()
        if room_id is not None:
            scopes.append((Room, room_id, "Room"))
    for model, pk, label in scopes:
        window = (
            ResourceDowntime.objects.for_resources(model, (pk,))
            .overlapping(starts_at, ends_at)
            .order_by("starts_at", "pk")
            .first()
        )
        if window is not None:
            until = "until further notice" if window.ends_at is None else f"until {window.ends_at:%Y-%m-%d %H:%M}"
            return f"{label} is {window.get_condition_display().lower()} ({window.reason}) {until}."
    return None


def project_exists(*, project_id) -> bool:
    return LabProject.objects.filter(pk=project_id).exists()


def bench_booking_summary(*, bench_id: int, evaluated_at: datetime) -> dict[str, Any]:
    """Bounded reserving schedule read under the existing authenticated-read policy.

    Read only schedule and project reference columns, never reasons or approvers.
    No reconciliation or lifecycle transitions occur on this read boundary.
    """
    reserving = BenchBooking.objects.filter(
        bench_id=bench_id,
        status__in=Booking.ACTIVE_STATUSES,
        approval_status__in=Booking.RESERVING_APPROVAL_STATUSES,
    ).order_by("starts_at", "pk")
    current = reserving.filter(starts_at__lte=evaluated_at, ends_at__gt=evaluated_at)
    count = current.count()
    columns = (
        "id",
        "booking_code",
        "starts_at",
        "ends_at",
        "status",
        "approval_status",
        "project_id",
        "project__project_name",
    )

    def project(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "booking_code": row["booking_code"],
            "starts_at": row["starts_at"],
            "ends_at": row["ends_at"],
            "status": {"value": row["status"], "label": str(BookingStatus(row["status"]).label)},
            "approval_status": {
                "value": row["approval_status"],
                "label": str(BookingApprovalStatus(row["approval_status"]).label),
            },
            "project": {"id": row["project_id"], "name": row["project__project_name"]}
            if row["project_id"] is not None
            else None,
        }

    next_row = reserving.filter(starts_at__gt=evaluated_at).values(*columns).first()
    return {
        "evaluated_at": evaluated_at,
        "current_reservations": [project(row) for row in current.values(*columns)[:5]],
        "current_reservations_count": count,
        "is_current_reservations_complete": count <= 5,
        "next_reservation": project(next_row) if next_row is not None else None,
    }
