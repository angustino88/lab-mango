"""Bounded keyset collectors; repeated pages deduplicate durably."""

from datetime import datetime, timedelta
from time import monotonic

from django.conf import settings
from django.db import transaction

from core.labs.features.equipment.public import inactive_equipment_candidates
from core.labs.models import BenchBooking, BookingApprovalStatus, BookingStatus

from ..contracts import scheduled_start_is_due
from .notification_intents import notifications_enabled, record_notification


def start_eligible(*, booking: BenchBooking, now: datetime) -> bool:
    cutoff = settings.BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF
    return (
        cutoff is not None
        and booking.starts_at >= cutoff
        and booking.approval_status == BookingApprovalStatus.APPROVED
        and booking.status in (BookingStatus.RESERVED, BookingStatus.IN_PROGRESS)
        and scheduled_start_is_due(starts_at=booking.starts_at, ends_at=booking.ends_at, now=now)
    )


def collect_notifications(
    *, now: datetime, after_booking_id: int = 0, after_equipment_id: int = 0, time_budget: float = 35
) -> dict[str, int]:
    deadline = monotonic() + time_budget
    if not notifications_enabled(now=now):
        return {"created": 0, "booking_cursor": -1, "equipment_cursor": -1}
    cutoff = settings.BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF
    if cutoff is None:
        return {"created": 0, "booking_cursor": -1, "equipment_cursor": -1}
    booking_ids = (
        list(
            BenchBooking.objects.filter(
                pk__gt=after_booking_id,
                starts_at__gte=max(cutoff, now - timedelta(minutes=10)),
                starts_at__lte=now,
                ends_at__gt=now,
                approval_status=BookingApprovalStatus.APPROVED,
                status__in=(BookingStatus.RESERVED, BookingStatus.IN_PROGRESS),
            )
            .order_by("pk")
            .values_list("pk", flat=True)[:100]
        )
        if after_booking_id >= 0
        else []
    )
    created = 0
    booking_cursor = after_booking_id
    for booking_id in booking_ids:
        if monotonic() >= deadline:
            return {"created": created, "booking_cursor": booking_cursor, "equipment_cursor": after_equipment_id}
        with transaction.atomic():
            booking = BenchBooking.objects.select_for_update().select_related("bench").get(pk=booking_id)
            if start_eligible(booking=booking, now=now):
                created += record_notification(
                    booking=booking,
                    kind="start",
                    logical_key=booking.starts_at.isoformat(),
                    now=now,
                )
        booking_cursor = booking_id
    booking_cursor = booking_cursor if len(booking_ids) == 100 else -1
    if monotonic() >= deadline:
        return {"created": created, "booking_cursor": booking_cursor, "equipment_cursor": after_equipment_id}
    candidates = inactive_equipment_candidates(now=now, after_id=after_equipment_id) if after_equipment_id >= 0 else []
    equipment_cursor = after_equipment_id
    for candidate in candidates:
        if monotonic() >= deadline:
            return {"created": created, "booking_cursor": booking_cursor, "equipment_cursor": equipment_cursor}
        if candidate.inactive_at < cutoff:
            equipment_cursor = candidate.equipment_id
            continue
        with transaction.atomic():
            candidate_booking = (
                BenchBooking.objects.select_for_update()
                .filter(
                    booking_code=candidate.booking_code,
                    bench_id=candidate.bench_id,
                    starts_at__lte=candidate.inactive_at,
                    ends_at__gt=now,
                    status=BookingStatus.IN_PROGRESS,
                    approval_status=BookingApprovalStatus.APPROVED,
                )
                .first()
            )
            fresh = inactive_equipment_candidates(now=now, equipment_id=candidate.equipment_id, limit=1)
            if candidate_booking and fresh and fresh[0] == candidate:
                created += record_notification(
                    booking=candidate_booking,
                    kind="inactive",
                    now=now,
                    equipment_id=candidate.equipment_id,
                    bench_name=candidate.bench_name,
                    equipment_name=candidate.equipment_name,
                    inactive_at=candidate.inactive_at,
                    logical_key=f"{candidate.equipment_id}:{candidate.inactive_at.isoformat()}",
                )
        equipment_cursor = candidate.equipment_id
    return {
        "created": created,
        "booking_cursor": booking_cursor,
        "equipment_cursor": equipment_cursor if len(candidates) == 100 else -1,
    }
