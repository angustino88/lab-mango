"""Bench projections never create equipment, statuses, or audit records."""

from django.db.models import (
    BooleanField,
    Case,
    CharField,
    Count,
    Exists,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce

from core.labs.features.equipment.public import bench_assignment_subquery, bench_computers
from core.labs.models import Bench, BenchFavorite, BenchGroup, BenchType, ResourceLifecycleStatus, Station
from core.labs.models.resource.base.availability import with_bench_state
from core.labs.models.resource.equipment.assignment import EquipmentAssignment


def list_benches(*, actor=None, setup_location=None, bench_group=None, type=None,
                 lifecycle_status=None, favorite=None, search=None):
    queryset = Bench.objects.select_related(
        "type", "bench_group", "owner", "group", "department", "station_slot", "setup_location",
        "setup_location__room__country", "setup_location__room__city", "setup_location__room__building",
    )
    if actor is not None and getattr(actor, "is_authenticated", False):
        queryset = queryset.annotate(is_favorite=Exists(BenchFavorite.objects.filter(user=actor, bench_id=OuterRef("pk"))))
    else:
        queryset = queryset.annotate(is_favorite=Value(False, output_field=BooleanField()))
    for field, value in (
        ("setup_location_id", setup_location), ("bench_group_id", bench_group),
        ("type_id", type), ("lifecycle_status", lifecycle_status), ("is_favorite", favorite),
    ):
        if value is not None:
            queryset = queryset.filter(**{field: value})
    if search:
        queryset = queryset.filter(Q(sku__icontains=search) | Q(name__icontains=search) | Q(description__icontains=search))
    # Condition, availability inputs and activity are computed per row (one correlated subquery each).
    queryset = with_bench_state(queryset)
    return queryset.annotate(
        equipment_count=Count(
            "equipment_assignments",
            filter=Q(
                equipment_assignments__unassigned_at__isnull=True,
                equipment_assignments__equipment__deleted_at__isnull=True,
            ),
            distinct=True,
        )
    ).order_by("sku", "pk")


def list_bench_options(
    *,
    actor=None,
    setup_location_id=None,
    bench_group_id=None,
    type_id=None,
    lifecycle_status=None,
    favorite=None,
    q=None,
    search=None,
    include_ids=None,
):
    """Return bench selector options, projecting only id, sku, and name (OPT-8).

    Reserved for selector data. Ordered by name, id (OPT-7).
    """
    search_term = q or search
    cond = Q(deleted_at__isnull=True)
    if setup_location_id is not None:
        cond &= Q(setup_location_id=setup_location_id)
    if bench_group_id is not None:
        cond &= Q(bench_group_id=bench_group_id)
    if type_id is not None:
        cond &= Q(type_id=type_id)
    queryset = Bench.objects.all()
    if lifecycle_status is not None:
        cond &= Q(lifecycle_status=lifecycle_status)
    if search_term:
        cond &= (Q(sku__icontains=search_term) | Q(name__icontains=search_term) | Q(description__icontains=search_term))
    if favorite is not None:
        if actor is not None and getattr(actor, "is_authenticated", False):
            bookmarks = BenchFavorite.objects.filter(user=actor, bench_id=OuterRef("pk"))
            cond &= (Q(Exists(bookmarks)) if favorite else ~Q(Exists(bookmarks)))
        elif favorite:
            return Bench.objects.none()

    if include_ids:
        query_filter = cond | Q(pk__in=include_ids)
    else:
        query_filter = cond

    return (
        queryset.filter(query_filter)
        .only("id", "sku", "name")
        .order_by("name", "id")
    )


def list_bench_equipment(*, bench_id):
    return EquipmentAssignment.objects.filter(
        bench_id=bench_id,
        unassigned_at__isnull=True,
        equipment__deleted_at__isnull=True,
    ).select_related("equipment", "equipment__kind").order_by("position", "pk")


def get_bench(*, bench_id, actor=None):
    return list_benches(actor=actor).get(pk=bench_id)


def get_bench_for_mapping(*, bench_id):
    """Return only an active bench row for the cross-resource mapping read boundary."""
    return Bench.objects.filter(pk=bench_id, deleted_at__isnull=True).only(
        "id", "uid", "sku", "name", "setup_location_id", "station_slot_id"
    ).values("id", "uid", "sku", "name", "setup_location_id", "station_slot_id").first()


def bench_mapping_rows(*, bench_ids=(), station_ids=(), room_ids=()):
    queryset = Bench.objects.filter(deleted_at__isnull=True)
    if bench_ids:
        queryset = queryset.filter(pk__in=bench_ids)
    elif station_ids:
        queryset = queryset.filter(setup_location_id__in=station_ids)
    elif room_ids:
        queryset = queryset.filter(setup_location__room_id__in=room_ids, setup_location__deleted_at__isnull=True)
    else:
        return queryset.none().values("id", "uid", "sku", "name", "setup_location_id", "station_slot_id")
    return queryset.order_by("pk").values("id", "uid", "sku", "name", "setup_location_id", "station_slot_id")


MAPPING_FULLY_MAPPED = "fully_mapped"
MAPPING_NEEDS_EQUIPMENT = "needs_equipment"
MAPPING_NEEDS_PLACEMENT = "needs_placement"
MAPPING_STATES = (MAPPING_FULLY_MAPPED, MAPPING_NEEDS_EQUIPMENT, MAPPING_NEEDS_PLACEMENT)


def bench_mapping_list(*, q=None, room_id=None, station_id=None, bench_id=None, equipment_category_id=None):
    """Active benches with their mapping completeness, ordered by SKU, for the bench-rooted mapping list.

    Annotations: ``mapping_has_station``, ``mapping_has_room`` (through a live station), ``mapping_equipment_count``
    (units placed on the bench now) and ``mapping_state``: ``needs_placement`` (no live station in a live room),
    ``needs_equipment`` (placed, nothing on it) or ``fully_mapped``. ``q`` matches the bench, its station, its room
    and the units on it (SKU or name). Each count and match is one correlated subquery, never a query per row.
    """
    placed = Q(setup_location__isnull=False, setup_location__deleted_at__isnull=True)
    in_room = placed & Q(setup_location__room__isnull=False, setup_location__room__deleted_at__isnull=True)
    units = (
        bench_assignment_subquery().order_by().values("bench_id").annotate(units=Count("pk")).values("units")
    )
    queryset = Bench.objects.filter(deleted_at__isnull=True).annotate(
        mapping_has_station=Case(When(placed, then=Value(True)), default=Value(False), output_field=BooleanField()),
        mapping_has_room=Case(When(in_room, then=Value(True)), default=Value(False), output_field=BooleanField()),
        mapping_equipment_count=Coalesce(Subquery(units, output_field=IntegerField()), Value(0)),
    ).annotate(
        mapping_state=Case(
            When(mapping_has_room=False, then=Value(MAPPING_NEEDS_PLACEMENT)),
            When(mapping_equipment_count=0, then=Value(MAPPING_NEEDS_EQUIPMENT)),
            default=Value(MAPPING_FULLY_MAPPED),
            output_field=CharField(),
        )
    )
    if bench_id is not None:
        queryset = queryset.filter(pk=bench_id)
    if station_id is not None:
        queryset = queryset.filter(setup_location_id=station_id)
    if room_id is not None:
        queryset = queryset.filter(setup_location__room_id=room_id, setup_location__deleted_at__isnull=True)
    if equipment_category_id is not None:
        queryset = queryset.filter(Exists(bench_assignment_subquery(category_id=equipment_category_id)))
    if q:
        queryset = queryset.filter(
            Q(sku__icontains=q)
            | Q(name__icontains=q)
            | Q(description__icontains=q)
            | Q(setup_location__sku__icontains=q)
            | Q(setup_location__name__icontains=q)
            | Q(setup_location__room__sku__icontains=q)
            | Q(setup_location__room__name__icontains=q)
            | Q(Exists(bench_assignment_subquery(search=q)))
        )
    return queryset.order_by("sku", "pk")


def bench_mapping_summary(queryset):
    """Counts over a ``bench_mapping_list`` queryset, in one aggregate query."""
    totals = queryset.order_by().aggregate(
        benches=Count("pk"),
        fully_mapped=Count("pk", filter=Q(mapping_state=MAPPING_FULLY_MAPPED)),
        needs_equipment=Count("pk", filter=Q(mapping_state=MAPPING_NEEDS_EQUIPMENT)),
        needs_placement=Count("pk", filter=Q(mapping_state=MAPPING_NEEDS_PLACEMENT)),
        equipment=Sum("mapping_equipment_count"),
    )
    return {key: value or 0 for key, value in totals.items()}


def list_booking_bench_choices(*, q=None, include_ids=None, has_computing=None):
    """Benches a person picks when booking: in-service benches, with the computers on each (name, hostname).

    People know the computer they remote into, not the bench SKU, so ``q`` also matches a computer's name, SKU
    or hostname. ``has_computing=True`` keeps only benches with a computer placed on them. ``include_ids`` adds benches regardless of state (an existing booking's bench). Ordered by name.
    Two queries: the benches, then their computers.
    """
    queryset = Bench.objects.filter(deleted_at__isnull=True, lifecycle_status=ResourceLifecycleStatus.IN_SERVICE)
    if q:
        computer_match = bench_assignment_subquery(search=q) | bench_assignment_subquery().filter(
            equipment__computing_profile__hostname__icontains=q
        )
        queryset = queryset.filter(Q(sku__icontains=q) | Q(name__icontains=q) | Q(Exists(computer_match)))
    if has_computing is not None:
        has_computer = Exists(bench_assignment_subquery().filter(equipment__kind__category__monitored=True))
        queryset = queryset.filter(has_computer if has_computing else ~has_computer)
    if include_ids:
        queryset = queryset | Bench.objects.filter(pk__in=include_ids, deleted_at__isnull=True)
    benches = list(queryset.distinct().order_by("name", "pk").values("id", "sku", "name"))
    computers = bench_computers(bench_ids=[bench["id"] for bench in benches])
    return [{**bench, "computers": computers.get(bench["id"], [])} for bench in benches]


def reference_data():
    return {
        "types": BenchType.objects.filter(active=True).order_by("name", "pk"),
        "groups": BenchGroup.objects.filter(active=True).order_by("name", "pk"),
        "stations": Station.objects.order_by("sku", "pk"),
        "lifecycle_statuses": [
            {"value": value, "label": str(label)} for value, label in ResourceLifecycleStatus.choices
        ],
    }


def list_references(*, model):
    model = _reference_model(model)
    if model is None:
        raise ValueError("Unsupported bench reference model.")
    return model.objects.order_by("name", "pk")


def get_reference(*, model, reference_id):
    model = _reference_model(model)
    if model is None:
        raise ValueError("Unsupported bench reference model.")
    return model.objects.get(pk=reference_id)


def _reference_model(model):
    if model in ("group", BenchGroup):
        return BenchGroup
    if model in ("type", BenchType):
        return BenchType
    return None


__all__ = [
    "bench_station_ids",
    "get_bench", "get_bench_for_mapping", "get_reference", "list_bench_equipment", "list_bench_options", "list_benches",
    "bench_mapping_rows", "bench_mapping_list", "bench_mapping_summary", "list_booking_bench_choices",
    "MAPPING_STATES",
    "list_references", "reference_data",
]


def bench_station_ids(*, bench_ids) -> dict[int, int]:
    """Station of each live bench that sits in a station slot of a live station, in one query.

    Benches without a station slot are absent: they have no physical placement (telemetry rejects them).
    """
    return dict(
        Bench.objects.filter(
            pk__in=bench_ids, station_slot__isnull=False, station_slot__station__deleted_at__isnull=True
        ).values_list("pk", "station_slot__station_id")
    )
