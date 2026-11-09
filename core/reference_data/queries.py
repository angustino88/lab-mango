"""Bounded by the caller's paginator; deterministic reference catalog selectors."""

from typing import Any

from django.db.models import Q, QuerySet

from .contracts import ReferenceResource
from .exceptions import ReferenceNotFound
from .policies import ensure_access


def list_references(resource: ReferenceResource, *, actor: Any, filters: dict[str, Any]) -> QuerySet:
    ensure_access(resource, actor)
    queryset = resource.model.objects.all().order_by(resource.label, "pk")
    many = [name for name in resource.fields if resource.model._meta.get_field(name).many_to_many]
    if many:
        queryset = queryset.prefetch_related(*many)
    search = filters.get("search")
    if search:
        queryset = queryset.filter(Q(**{f"{resource.label}__icontains": search}))
    for name in resource.fields:
        field = resource.model._meta.get_field(name)
        if field.many_to_one and filters.get(field.attname) is not None:
            queryset = queryset.filter(**{field.attname: filters[field.attname]})
    if "active" in resource.fields and filters.get("active") is not None:
        queryset = queryset.filter(active=filters["active"])
    return queryset


def get_reference(resource: ReferenceResource, *, actor: Any, reference_id: int) -> Any:
    instance = list_references(resource, actor=actor, filters={}).filter(pk=reference_id).first()
    if instance is None:
        raise ReferenceNotFound()
    return instance
