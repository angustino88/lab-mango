"""Location-owned geographic reference and selector reads (ADR 002)."""

from typing import Any

from django.db.models import CharField, F, Q, QuerySet, Value

from core.labs.models import Building, City, Country, Room, Station, StationType
from core.reference_data.contracts import ReferenceResource
from core.reference_data.public import get_reference, list_references


def list_catalog_references(resource: ReferenceResource, *, actor: Any, filters: dict[str, Any]) -> QuerySet:
    return list_references(resource, actor=actor, filters=filters)


def get_catalog_reference(resource: ReferenceResource, *, actor: Any, reference_id: int) -> Any:
    return get_reference(resource, actor=actor, reference_id=reference_id)


def list_countries(*, search: str | None = None) -> QuerySet[Country]:
    qs = Country.objects.all().order_by("name", "pk")
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))
    return qs


def get_country(*, country_id: int) -> Country:
    return Country.objects.get(pk=country_id)


def list_country_options(*, actor: Any = None, q: str | None = None, include_ids: list[int] | None = None) -> QuerySet:
    cond = Q()
    if q:
        cond &= (Q(name__icontains=q) | Q(code__icontains=q))
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        Country.objects.filter(cond)
        .annotate(sku=F("code"))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


def list_cities(*, search: str | None = None, country_id: int | None = None) -> QuerySet[City]:
    qs = City.objects.select_related("country").order_by("name", "pk")
    if country_id is not None:
        qs = qs.filter(country_id=country_id)
    if search:
        qs = qs.filter(name__icontains=search)
    return qs


def get_city(*, city_id: int) -> City:
    return City.objects.select_related("country").get(pk=city_id)


def list_city_options(
    *, actor: Any = None, q: str | None = None, country_id: int | None = None, include_ids: list[int] | None = None
) -> QuerySet:
    cond = Q()
    if country_id is not None:
        cond &= Q(country_id=country_id)
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        City.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


def list_buildings(*, search: str | None = None, city_id: int | None = None) -> QuerySet[Building]:
    qs = Building.objects.select_related("city", "city__country").order_by("name", "pk")
    if city_id is not None:
        qs = qs.filter(city_id=city_id)
    if search:
        qs = qs.filter(name__icontains=search)
    return qs


def get_building(*, building_id: int) -> Building:
    return Building.objects.select_related("city", "city__country").get(pk=building_id)


def list_building_options(
    *, actor: Any = None, q: str | None = None, city_id: int | None = None, include_ids: list[int] | None = None
) -> QuerySet:
    cond = Q()
    if city_id is not None:
        cond &= Q(city_id=city_id)
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        Building.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


def list_room_options(
    *,
    actor: Any = None,
    q: str | None = None,
    building_id: int | None = None,
    city_id: int | None = None,
    include_ids: list[int] | None = None,
) -> QuerySet:
    cond = Q(deleted_at__isnull=True)
    if building_id:
        cond &= Q(building_id=building_id)
    if city_id:
        cond &= Q(city_id=city_id)
    if q:
        cond &= (Q(sku__icontains=q) | Q(name__icontains=q))
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        Room.objects.filter(cond)
        .only("id", "sku", "name")
        .order_by("name", "id")
    )


def list_station_options(
    *,
    actor: Any = None,
    q: str | None = None,
    room_id: int | None = None,
    station_type_id: int | None = None,
    include_ids: list[int] | None = None,
) -> QuerySet:
    cond = Q(deleted_at__isnull=True)
    if room_id:
        cond &= Q(room_id=room_id)
    if station_type_id:
        cond &= Q(type_id=station_type_id)
    if q:
        cond &= (Q(sku__icontains=q) | Q(name__icontains=q))
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        Station.objects.filter(cond)
        .only("id", "sku", "name")
        .order_by("name", "id")
    )


def list_station_type_options(*, actor: Any = None, q: str | None = None, include_ids: list[int] | None = None) -> QuerySet:
    cond = Q()
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        StationType.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )
