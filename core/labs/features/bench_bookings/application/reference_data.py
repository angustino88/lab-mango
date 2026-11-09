"""Booking-owned project import command."""

from typing import Any

from core.reference_data.contracts import CreateReferenceInput, ReferenceResource, ReferenceResult
from core.reference_data.public import create_reference


def create_catalog_reference(
    resource: ReferenceResource, *, values: dict[str, Any], idempotency_key: str, actor: Any
) -> ReferenceResult:
    return create_reference(resource, CreateReferenceInput(values, idempotency_key), actor=actor)
