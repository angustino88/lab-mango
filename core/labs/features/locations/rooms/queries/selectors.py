"""Room projections: lifecycle and access policy are stored; condition, activity, availability and the
deprecated ``status`` are computed (``with_location_state``). History lives in status records."""

from django.db.models import Exists, OuterRef, Q

from core.labs.models.resource.base.availability import with_location_state
from core.labs.models.resource.location.room import Room, RoomStatusRecord
from core.labs.models.resource.location.room_observation import RoomObservation
from core.labs.models.resource.location.room_slot import RoomSlot
from core.labs.models.resource.location.station import Station


def list_rooms(*, search=None):
    queryset = with_location_state(Room.objects.select_related("country", "city", "building"), "room").order_by("sku", "pk")
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
        "id", "room_id", "room__name", "room__sku", "row_index", "col_index", "slot_code", "x_mm", "y_mm",
        "width_mm", "depth_mm", "orientation_degrees"
    )


def list_room_slots(*, room_id):
    Room.objects.only("pk").get(pk=room_id)
    occupied = Station.objects.filter(slot_id=OuterRef("pk"), deleted_at__isnull=True)
    return RoomSlot.objects.filter(room_id=room_id).annotate(occupied=Exists(occupied)).order_by(
        "row_index", "col_index", "pk"
    )


def room_status_history(*, room_id):
    Room.objects.only("pk").get(pk=room_id)
    return RoomStatusRecord.objects.filter(room_id=room_id).select_related("creator").order_by("-created", "-pk")


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
