"""Explicit equipment relationship dimensions and SQL inventory aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from django.db.models import Count, F, QuerySet, Subquery

from core.labs.models import Equipment


@dataclass(frozen=True)
class RelationshipDimension:
    """Server-owned relationship paths; never inferred from client input."""

    id_path: str
    name_path: str
    parents: tuple[str, ...] = ()


EQUIPMENT_DIMENSIONS = MappingProxyType(
    {
        "category": RelationshipDimension("kind__category_id", "kind__category__name"),
        "kind": RelationshipDimension("kind_id", "kind__name", ("category",)),
        "type": RelationshipDimension("type_id", "type__name", ("kind",)),
        "manufacturer": RelationshipDimension("manufacturer_id", "manufacturer__name", ("category",)),
        "product_model_id": RelationshipDimension("product_model_id", "product_model__name", ("type", "manufacturer")),
        "department_id": RelationshipDimension("department_id", "department__name"),
        "group_id": RelationshipDimension("group_id", "group__name", ("department_id",)),
    }
)


def equipment_facet_rows(*, population: QuerySet, dimension: str) -> QuerySet[Equipment, dict[str, Any]]:
    """Group the complete filtered list population, independent of list pagination.

    A membership subquery isolates category/search joins and list annotations from
    aggregation. PK-IN membership collapses M2M duplicates; the configured outer
    dimensions traverse only single-valued forward relations (pinned by tests).
    This read inherits the caller's list visibility and also excludes deleted rows.
    No catalog active predicate is applied: historical inventory remains visible.
    """
    configured = EQUIPMENT_DIMENSIONS[dimension]
    matching_ids = population.order_by().values("pk")
    return (
        Equipment.objects.filter(deleted_at__isnull=True, pk__in=Subquery(matching_ids))
        .order_by()
        .values(facet_id=F(configured.id_path), facet_name=F(configured.name_path))
        .annotate(equipment_count=Count("pk"))
        .order_by(F("facet_name").asc(nulls_last=True), F("facet_id").asc(nulls_last=True))
    )
