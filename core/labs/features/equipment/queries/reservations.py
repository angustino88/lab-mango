"""Read-only reservation queries."""

from datetime import datetime

from django.db.models import Q, QuerySet

from core.labs.models import BookingStatus, EquipmentBooking


def list_reservations(
    *,
    status: str | None = BookingStatus.RESERVED,
    equipment_id: int | None = None,
    batch_id: int | None = None,
    starts_before: datetime | None = None,
    ends_after: datetime | None = None,
    borrower_name: str | None = None,
) -> QuerySet[EquipmentBooking]:
    """Reservation lines made through the reservation commands, by start time. Page + count = 2 queries."""
    queryset = (
        EquipmentBooking.objects.filter(batch__isnull=False)
        .select_related("batch", "batch__borrower", "equipment")
        .order_by("starts_at", "pk")
    )
    if status:
        queryset = queryset.filter(status=status)
    if equipment_id is not None:
        queryset = queryset.filter(equipment_id=equipment_id)
    if batch_id is not None:
        queryset = queryset.filter(batch_id=batch_id)
    if starts_before is not None:
        queryset = queryset.filter(starts_at__lt=starts_before)
    if ends_after is not None:
        queryset = queryset.filter(ends_at__gt=ends_after)
    if borrower_name:
        queryset = queryset.filter(
            Q(batch__borrower_name__icontains=borrower_name)
            | Q(batch__borrower__display_name__icontains=borrower_name)
            | Q(batch__borrower__username__icontains=borrower_name)
        )
    return queryset


__all__ = ("list_reservations",)
