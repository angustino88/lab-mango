"""Bench-owned reference import and selector reads (ADR 002)."""

from typing import Any

from django.db.models import CharField, Q, QuerySet, Value

from core.labs.models import BenchGroup, BenchType
from core.reference_data.contracts import ReferenceResource
from core.reference_data.public import get_reference, list_references


def list_catalog_references(resource: ReferenceResource, *, actor: Any, filters: dict[str, Any]) -> QuerySet:
    return list_references(resource, actor=actor, filters=filters)


def get_catalog_reference(resource: ReferenceResource, *, actor: Any, reference_id: int) -> Any:
    return get_reference(resource, actor=actor, reference_id=reference_id)


def list_bench_group_options(*, actor: Any = None, q: str | None = None, include_ids: list[int] | None = None) -> QuerySet:
    cond = Q(active=True)
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        BenchGroup.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


def list_bench_type_options(*, actor: Any = None, q: str | None = None, include_ids: list[int] | None = None) -> QuerySet:
    cond = Q(active=True)
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        BenchType.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )
