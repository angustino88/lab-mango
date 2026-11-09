"""Booking-owned import reference selectors."""

from typing import Any

from django.db.models import QuerySet

from core.reference_data.contracts import ReferenceResource
from core.reference_data.public import get_reference, list_references


def list_catalog_references(resource: ReferenceResource, *, actor: Any, filters: dict[str, Any]) -> QuerySet:
    return list_references(resource, actor=actor, filters=filters)


def get_catalog_reference(resource: ReferenceResource, *, actor: Any, reference_id: int) -> Any:
    return get_reference(resource, actor=actor, reference_id=reference_id)
