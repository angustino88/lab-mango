"""Computed availability, activity and legacy status of rooms, stations and benches (never stored).

Design: ``docs/proposals/resource-status-and-downtime.md``. Two directions through the hierarchy
room → station → bench:

* **Problems pass down.** A bench is unavailable when it, its station or its room is not in service or
  not operational (``availability``). ``blocked_by`` names the resource that blocks.
* **Activity passes up.** A bench is ``active`` when a booking is in progress or a computing unit placed
  on it reports live activity (``ComputingActivity.status = active``); a station when any of its
  benches is, a room when any bench at one of its stations is (``activity_expression``).

These helpers build SQL expressions and pure functions only; features own the querysets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from django.db.models import Case, CharField, Exists, OuterRef, Q, Value, When
from django.utils import timezone

from core.common.domain.errors import DetailMessage
from core.labs.models.activity.computing_activity import ComputingActivityStatus
from core.labs.models.booking.base import BookingApprovalStatus, BookingStatus
from core.labs.models.booking.bench_booking import BenchBooking
from core.labs.models.booking.equipment_booking import EquipmentBooking
from core.labs.models.resource.base.downtime import (
    ResourceDowntime,
    condition_expression,
    downtime_reason_expression,
)
from core.labs.models.resource.base.status import (
    LegacyLocationStatus,
    ResourceAccessPolicy,
    ResourceActivityStatus,
    ResourceAvailability,
    ResourceCondition,
    ResourceLifecycleStatus,
)
from core.labs.models.resource.equipment.assignment import EquipmentAssignment
from core.labs.models.resource.location.room import Room
from core.labs.models.resource.location.station import Station

# Which bench bookings belong to an outer row, per outer resource type.
_BOOKING_SCOPE = {
    "bench": "bench_id",
    "station": "bench__setup_location_id",
    "room": "bench__setup_location__room_id",
}


def _end_of_today(now: datetime) -> datetime:
    tomorrow = timezone.localdate(now) + timedelta(days=1)
    return timezone.make_aware(datetime.combine(tomorrow, time.min))


def activity_expression(resource_type: str, *, now: datetime | None = None) -> Case:
    """Annotation: ``active`` (a booking in progress, or live activity reported by a computing unit on
    a bench), ``scheduled`` (an approved reserved booking later today), else ``idle``. Rolls up from
    benches to their station and room.
    """
    now = now or timezone.now()
    scope = {_BOOKING_SCOPE[resource_type]: OuterRef("pk")}
    bookings = BenchBooking.objects.filter(**scope, bench__deleted_at__isnull=True)
    in_progress = bookings.filter(status=BookingStatus.IN_PROGRESS)
    # Monitoring: the agent on a computing unit placed on the bench reports someone using it.
    live = EquipmentAssignment.objects.filter(
        **scope,
        bench__deleted_at__isnull=True,
        unassigned_at__isnull=True,
        equipment__deleted_at__isnull=True,
        equipment__activity__status=ComputingActivityStatus.ACTIVE,
    )
    later_today = bookings.filter(
        status=BookingStatus.RESERVED,
        approval_status=BookingApprovalStatus.APPROVED,
        starts_at__lt=_end_of_today(now),
        ends_at__gt=now,
    )
    return Case(
        When(Exists(in_progress) | Exists(live), then=Value(ResourceActivityStatus.ACTIVE.value)),
        When(Exists(later_today), then=Value(ResourceActivityStatus.SCHEDULED.value)),
        default=Value(ResourceActivityStatus.IDLE.value),
        output_field=CharField(),
    )


def bench_bookings_blocked_by_parents(*, bench_ids, station, room) -> list[int]:
    """Reserving bench bookings (ending after now) that the new parents would block (design rule 3).

    Used when a bench moves to ``station`` or a station moves to ``room``: every booking is blocked when a
    parent is not in service, otherwise the bookings that overlap a downtime window of a parent. The
    caller holds the station lock and the bench locks. Two queries at most (windows, bookings).
    """
    if station is None or not bench_ids:
        return []
    now = timezone.now()
    bookings = BenchBooking.objects.filter(
        bench_id__in=bench_ids,
        status__in=BenchBooking.ACTIVE_STATUSES,
        approval_status__in=BenchBooking.RESERVING_APPROVAL_STATUSES,
        ends_at__gt=now,
    ).order_by("pk")
    parents = [parent for parent in (station, room) if parent is not None]
    if any(parent.lifecycle_status != ResourceLifecycleStatus.IN_SERVICE for parent in parents):
        return list(bookings.values_list("pk", flat=True))
    windows = ResourceDowntime.objects.get_queryset().none()
    for parent in parents:
        windows = windows | ResourceDowntime.objects.for_resources(type(parent), (parent.pk,))
    overlap = Q(pk__in=[])
    for starts_at, ends_at in (
        windows.not_cancelled()
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
        .values_list("starts_at", "ends_at")
    ):
        window = Q(ends_at__gt=starts_at)
        if ends_at is not None:
            window &= Q(starts_at__lt=ends_at)
        overlap |= window
    return list(bookings.filter(overlap).values_list("pk", flat=True))


def booking_conflict_details(*, bench_booking_ids=(), equipment_booking_ids=()) -> dict[str, Any]:
    """Error ``details`` naming each blocking booking: field ``bench_bookings.<id>`` / ``equipment_bookings.<id>``,
    code ``booking_overlaps_downtime``, and a readable message (booking code and local period). One query per type.
    """
    details: dict[str, Any] = {}
    for key, model, ids in (
        ("bench_bookings", BenchBooking, bench_booking_ids),
        ("equipment_bookings", EquipmentBooking, equipment_booking_ids),
    ):
        if not ids:
            continue
        rows = (
            model.objects.filter(pk__in=ids)
            .order_by("starts_at", "pk")
            .values_list("pk", "booking_code", "starts_at", "ends_at")
        )
        details[key] = {
            str(pk): DetailMessage(
                f"Booking {code} ({timezone.localtime(starts_at):%Y-%m-%d %H:%M} to "
                f"{timezone.localtime(ends_at):%Y-%m-%d %H:%M}) overlaps the downtime.",
                "booking_overlaps_downtime",
            )
            for pk, code, starts_at, ends_at in rows
        }
    return details


def legacy_status_expression(*, condition: str = "condition", activity: str = "activity_status") -> Case:
    """Annotation: the deprecated seven-value room/station ``status``, from the separate facts.

    Needs ``condition`` and ``activity_status`` annotations on the queryset (names configurable).
    """
    status = LegacyLocationStatus
    return Case(
        When(lifecycle_status=ResourceLifecycleStatus.RETIRED, then=Value(status.RETIRED.value)),
        When(lifecycle_status=ResourceLifecycleStatus.PLANNED, then=Value(status.CLOSED.value)),
        When(Q(**{condition: ResourceCondition.OUT_OF_SERVICE}), then=Value(status.ISSUE.value)),
        When(Q(**{condition: ResourceCondition.IN_MAINTENANCE}), then=Value(status.MAINTENANCE.value)),
        When(access_policy=ResourceAccessPolicy.RESTRICTED, then=Value(status.RESTRICTED.value)),
        When(
            Q(**{f"{activity}__in": (ResourceActivityStatus.ACTIVE, ResourceActivityStatus.SCHEDULED)}),
            then=Value(status.RESERVED.value),
        ),
        default=Value(status.AVAILABLE.value),
        output_field=CharField(),
    )


# The deprecated four-value bench ``status``: ``out_of_service`` is now an in-service bench with downtime.
LEGACY_BENCH_STATUSES = (
    *[(value, label) for value, label in ResourceLifecycleStatus.choices if value != ResourceLifecycleStatus.RETIRED],
    (ResourceCondition.OUT_OF_SERVICE.value, ResourceCondition.OUT_OF_SERVICE.label),
    (ResourceLifecycleStatus.RETIRED.value, ResourceLifecycleStatus.RETIRED.label),
)


def legacy_bench_status_expression(*, condition: str = "condition") -> Case:
    """Annotation: the deprecated bench ``status`` (``planned``, ``in_service``, ``out_of_service``, ``retired``)."""
    return Case(
        When(
            Q(lifecycle_status=ResourceLifecycleStatus.IN_SERVICE) & ~Q(**{condition: ResourceCondition.OPERATIONAL}),
            then=Value(ResourceCondition.OUT_OF_SERVICE.value),
        ),
        default="lifecycle_status",
        output_field=CharField(),
    )


def with_bench_state(queryset, *, now: datetime | None = None):
    """Annotate a ``Bench`` queryset with its own and its parents' condition, its activity and legacy status.

    Callers ``select_related("setup_location__room")`` to read the parents' lifecycle without extra queries.
    """
    return queryset.annotate(
        condition=condition_expression(queryset.model),
        downtime_reason=downtime_reason_expression(queryset.model),
        station_condition=condition_expression(Station, outer_ref="setup_location_id"),
        station_downtime_reason=downtime_reason_expression(Station, outer_ref="setup_location_id"),
        room_condition=condition_expression(Room, outer_ref="setup_location__room_id"),
        room_downtime_reason=downtime_reason_expression(Room, outer_ref="setup_location__room_id"),
        activity_status=activity_expression("bench", now=now),
    ).annotate(legacy_status=legacy_bench_status_expression())


def with_location_state(queryset, resource_type: str, *, now: datetime | None = None):
    """Annotate a ``Room`` or ``Station`` queryset with condition, activity and the deprecated ``status``.

    A station also gets its room's condition (``room_condition``); select ``room`` for its lifecycle.
    """
    annotations = {
        "condition": condition_expression(queryset.model),
        "downtime_reason": downtime_reason_expression(queryset.model),
        "activity_status": activity_expression(resource_type, now=now),
    }
    if resource_type == "station":
        annotations["room_condition"] = condition_expression(Room, outer_ref="room_id")
        annotations["room_downtime_reason"] = downtime_reason_expression(Room, outer_ref="room_id")
    return queryset.annotate(**annotations).annotate(legacy_status=legacy_status_expression())


def bench_availability(bench: Any) -> dict[str, Any]:
    """``availability`` of a bench row from ``with_bench_state`` (self, then station, then room)."""
    chain = [level_of("bench", bench)]
    station = bench.setup_location
    if station is not None:
        chain.append(level_of("station", station, annotated=bench, prefix="station_"))
        if station.room is not None:
            chain.append(level_of("room", station.room, annotated=bench, prefix="room_"))
    return availability(chain)


def location_availability(resource_type: str, obj: Any) -> dict[str, Any]:
    """``availability`` of a room or station row from ``with_location_state``."""
    chain = [level_of(resource_type, obj)]
    if resource_type == "station" and obj.room is not None:
        chain.append(level_of("room", obj.room, annotated=obj, prefix="room_"))
    return availability(chain)


@dataclass(frozen=True, slots=True)
class HierarchyLevel:
    """One resource in a bench → station → room chain, with the facts availability reads."""

    resource_type: str
    resource_id: int
    name: str
    lifecycle_status: str
    condition: str
    downtime_reason: str | None = None


def availability(chain: list[HierarchyLevel]) -> dict[str, Any]:
    """``available``, or ``unavailable`` with the first blocking resource (self first, then parents)."""
    for level in chain:
        if level.lifecycle_status != ResourceLifecycleStatus.IN_SERVICE:
            reason = level.lifecycle_status
        elif level.condition != ResourceCondition.OPERATIONAL:
            reason = level.downtime_reason or level.condition
        else:
            continue
        return {
            "value": ResourceAvailability.UNAVAILABLE.value,
            "blocked_by": {"type": level.resource_type, "id": level.resource_id, "name": level.name},
            "condition": level.condition,
            "reason": reason,
        }
    return {"value": ResourceAvailability.AVAILABLE.value, "blocked_by": None, "condition": None, "reason": None}


def level_of(resource_type: str, obj: Any, *, annotated: Any = None, prefix: str = "") -> HierarchyLevel:
    """Build a level from a model row; ``<prefix>condition`` and ``<prefix>downtime_reason`` are read
    from ``annotated`` (default ``obj``), e.g. a bench row carrying its station's condition.
    """
    source = obj if annotated is None else annotated
    return HierarchyLevel(
        resource_type=resource_type,
        resource_id=obj.pk,
        name=obj.name or obj.sku,
        lifecycle_status=obj.lifecycle_status,
        condition=getattr(source, f"{prefix}condition", None) or ResourceCondition.OPERATIONAL,
        downtime_reason=getattr(source, f"{prefix}downtime_reason", None),
    )


__all__ = [
    "LEGACY_BENCH_STATUSES",
    "HierarchyLevel",
    "activity_expression",
    "bench_bookings_blocked_by_parents",
    "booking_conflict_details",
    "availability",
    "bench_availability",
    "legacy_bench_status_expression",
    "legacy_status_expression",
    "level_of",
    "location_availability",
    "with_bench_state",
    "with_location_state",
]
