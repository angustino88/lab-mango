"""Room projections; status is a correlated subquery, not a join."""

from django.db.models import OuterRef, Q, Subquery

from core.labs.models.resource.location.room import Room, RoomStatusRecord
from core.labs.models.resource.location.room_observation import RoomObservation
from core.labs.models.resource.location.room_slot import RoomSlot


def list_rooms(*, search=None):
    latest = RoomStatusRecord.objects.filter(room_id=OuterRef("pk")).order_by("-created", "-pk")
    queryset = Room.objects.select_related("country", "city", "building").annotate(
        current_status=Subquery(latest.values("status")[:1]),
    ).order_by("sku", "pk")
    if search:
        queryset = queryset.filter(Q(sku__icontains=search) | Q(name__icontains=search) | Q(label__icontains=search))
    return queryset


def get_room(*, room_id):
    return list_rooms().get(pk=room_id)


def get_room_for_mapping(*, room_id):
    """Return only an active room row for the cross-resource mapping read boundary."""
    return Room.objects.filter(pk=room_id, deleted_at__isnull=True).values("id", "uid", "sku", "name").first()


def room_mapping_rows(*, room_ids):
    return Room.objects.filter(pk__in=room_ids, deleted_at__isnull=True).order_by("pk").values(
        "id", "uid", "sku", "name", "layout_rows", "layout_columns"
    )


def room_slot_mapping_rows(*, room_ids):
    return RoomSlot.objects.filter(room_id__in=room_ids, room__deleted_at__isnull=True).order_by("pk").values(
        "id", "room_id", "row_index", "col_index", "slot_code", "x_mm", "y_mm", "width_mm",
        "depth_mm", "orientation_degrees"
    )


def list_room_slots(*, room_id):
    Room.objects.only("pk").get(pk=room_id)
    return RoomSlot.objects.filter(room_id=room_id).order_by("row_index", "col_index", "pk")


def room_status_history(*, room_id):
    Room.objects.only("pk").get(pk=room_id)
    return RoomStatusRecord.objects.filter(room_id=room_id).order_by("-created", "-pk")


def room_observations(*, room_id):
    Room.objects.only("pk").get(pk=room_id)
    return RoomObservation.objects.filter(room_id=room_id).order_by("-observed_at", "-pk")


__all__ = [
    "get_room",
    "get_room_for_mapping",
    "list_room_slots",
    "list_rooms",
    "room_mapping_rows",
    "room_observations",
    "room_slot_mapping_rows",
    "room_status_history",
]
