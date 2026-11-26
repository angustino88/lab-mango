"""Slot watch selectors; a user only ever sees their own watches."""

from django.db.models import QuerySet

from core.labs.models import BenchSlotWatch


def list_slot_watches(*, actor, status: str | None = None) -> QuerySet[BenchSlotWatch]:
    user_id = getattr(actor, "pk", None) if getattr(actor, "is_authenticated", False) else None
    if user_id is None:
        return BenchSlotWatch.objects.none()
    queryset = BenchSlotWatch.objects.filter(user_id=user_id).select_related("bench")
    if status:
        queryset = queryset.filter(status=status)
    return queryset.order_by("range_start", "pk")


def get_slot_watch(*, actor, watch_id: int) -> BenchSlotWatch:
    """The actor's watch, or ``DoesNotExist`` (404) for anyone else's."""
    return list_slot_watches(actor=actor).get(pk=watch_id)
