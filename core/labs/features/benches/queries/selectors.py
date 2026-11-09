"""Bench projections never create equipment, statuses, or audit records."""

from django.db.models import BooleanField, Count, Exists, OuterRef, Q, Value

from core.labs.models import Bench, BenchFavorite, BenchGroup, BenchType, Station
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
    status=None,
    favorite=None,
    q=None,
    search=None,
    include_ids=None,
):
    """Return bench selector options, projecting only id, sku, and name (OPT-8).

    Reserved for selector data. Ordered by name, id (OPT-7).
    """
    search_term = q or search
    status_val = lifecycle_status or status
    cond = Q(deleted_at__isnull=True)
    if setup_location_id is not None:
        cond &= Q(setup_location_id=setup_location_id)
    if bench_group_id is not None:
        cond &= Q(bench_group_id=bench_group_id)
    if type_id is not None:
        cond &= Q(type_id=type_id)
    if status_val is not None:
        cond &= Q(lifecycle_status=status_val)
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
        Bench.objects.filter(query_filter)
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


def reference_data():
    return {
        "types": BenchType.objects.filter(active=True).order_by("name", "pk"),
        "groups": BenchGroup.objects.filter(active=True).order_by("name", "pk"),
        "stations": Station.objects.order_by("sku", "pk"),
        "lifecycle_statuses": [{"value": value, "label": label} for value, label in Bench.LIFECYCLE_STATUSES],
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
    "get_bench", "get_bench_for_mapping", "get_reference", "list_bench_equipment", "list_bench_options", "list_benches",
    "bench_mapping_rows",
    "list_references", "reference_data",
]
