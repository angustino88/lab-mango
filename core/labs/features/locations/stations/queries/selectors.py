"""Station projections; correlated aggregates avoid bench/slot fan-out."""

from django.db.models import Count, IntegerField, OuterRef, Prefetch, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from core.labs.models.resource.bench.bench import Bench
from core.labs.models.resource.bench.bench_type import BenchType
from core.labs.models.resource.location.room import Room
from core.labs.models.resource.location.station import Station, StationStatus, StationStatusRecord, StationType
from core.labs.models.resource.location.station_slot import StationSlot


def list_station_slots(*, station_id):
    return StationSlot.objects.filter(station_id=station_id).prefetch_related("compatible_bench_types").order_by("position_index", "pk")


def list_stations(*, room_id=None, type_id=None, search=None, with_slots=False):
    benches = Bench.objects.filter(setup_location_id=OuterRef("pk")).order_by().values("setup_location_id")
    slots = StationSlot.objects.filter(
        station_id=OuterRef("pk"), is_active=True, status="available", bench__isnull=True,
    ).order_by().values("station_id")
    latest = StationStatusRecord.objects.filter(station_id=OuterRef("pk")).order_by("-created", "-pk")
    queryset = Station.objects.select_related(
        "type", "room__country", "room__city", "room__building", "slot",
    ).annotate(
        current_status=Subquery(latest.values("status")[:1]),
        active_bench_count=Coalesce(Subquery(benches.annotate(total=Count("pk")).values("total")), Value(0)),
        allocated_power_w=Coalesce(
            Subquery(benches.annotate(total=Sum("requested_power_w")).values("total")), Value(0),
            output_field=IntegerField(),
        ),
        available_slot_count=Coalesce(Subquery(slots.annotate(total=Count("pk")).values("total")), Value(0)),
        slot_count=Count("bench_slots", distinct=True),
    ).order_by("sku", "pk")
    if room_id is not None:
        queryset = queryset.filter(room_id=room_id)
    if type_id is not None:
        queryset = queryset.filter(type_id=type_id)
    if search:
        queryset = queryset.filter(Q(sku__icontains=search) | Q(name__icontains=search) | Q(label__icontains=search))
    if with_slots:
        queryset = queryset.prefetch_related(Prefetch(
            "bench_slots", queryset=StationSlot.objects.prefetch_related("compatible_bench_types").order_by("position_index", "pk"),
        ))
    return queryset


def get_station(*, station_id):
    return list_stations().get(pk=station_id)


def get_station_for_mapping(*, station_id):
    """Return only an active station row for the cross-resource mapping read boundary."""
    return Station.objects.filter(pk=station_id, deleted_at__isnull=True).only(
        "id", "uid", "sku", "name", "room_id", "slot_id"
    ).values("id", "uid", "sku", "name", "room_id", "slot_id").first()


def station_mapping_rows(*, station_ids=(), room_ids=()):
    queryset = Station.objects.filter(deleted_at__isnull=True)
    if station_ids:
        queryset = queryset.filter(pk__in=station_ids)
    elif room_ids:
        queryset = queryset.filter(room_id__in=room_ids)
    else:
        return queryset.none().values("id", "uid", "sku", "name", "room_id", "slot_id")
    return queryset.order_by("pk").values("id", "uid", "sku", "name", "room_id", "slot_id")


def station_slot_mapping_rows(*, station_ids=(), room_ids=()):
    queryset = StationSlot.objects.filter(station__deleted_at__isnull=True)
    if station_ids:
        queryset = queryset.filter(station_id__in=station_ids)
    elif room_ids:
        queryset = queryset.filter(station__room_id__in=room_ids)
    else:
        return queryset.none().values("id", "station_id", "position_index", "slot_code", "label")
    return queryset.order_by("pk").values("id", "station_id", "position_index", "slot_code", "label")


def station_history(*, station_id):
    Station.objects.only("pk").get(pk=station_id)
    return (
        StationStatusRecord.objects.filter(station_id=station_id).select_related("creator").order_by("-created", "-pk")
    )


def station_reference_data():
    return {
        "types": StationType.objects.order_by("name", "pk"),
        "bench_types": BenchType.objects.filter(active=True).order_by("name", "pk"),
        "rooms": Room.objects.only("id", "sku", "name").order_by("sku", "pk"),
        "statuses": [{"value": value, "label": str(label)} for value, label in StationStatus.choices],
        "slot_statuses": [{"value": value, "label": label} for value, label in StationSlot.STATUSES],
    }


def list_station_types():
    return StationType.objects.order_by("name", "pk")


def get_station_type(*, type_id):
    return StationType.objects.get(pk=type_id)


__all__ = [
    "get_station", "get_station_for_mapping", "get_station_type", "list_station_slots", "list_station_types", "list_stations",
    "station_history", "station_mapping_rows", "station_reference_data", "station_slot_mapping_rows",
]
