"""Equipment-owned catalog import command."""

from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction

from core.reference_data.contracts import CreateReferenceInput, ReferenceResource, ReferenceResult
from core.reference_data.exceptions import ReferencePermissionDenied, ReferenceValidationFailed
from core.reference_data.public import create_reference
from core.users.public import LabsRole, has_labs_role

# Equipment catalog reference data: lab-wide, written by lab administrators only (redesign OD12).
# Other lookups served here (departments, resource groups, materials, ...) keep the shared policy.
ADMIN_ONLY_CATALOG_MODELS = frozenset(
    {
        "equipmentcategory",
        "equipmentkind",
        "equipmenttype",
        "equipmentmanufacturer",
        "equipmentproductmodel",
        "specificationdefinition",
        "productmodelspecification",
    }
)


@transaction.atomic
def create_catalog_reference(
    resource: ReferenceResource, *, values: dict[str, Any], idempotency_key: str, actor: Any
) -> ReferenceResult:
    # The shared reference policy still applies the Django model permission on top of this.
    model_name = resource.model._meta.model_name
    if model_name in ADMIN_ONLY_CATALOG_MODELS and not has_labs_role(actor, LabsRole.ADMIN):
        raise ReferencePermissionDenied()
    if resource.model._meta.model_name == "productmodelspecification":
        # Decimal accepts NaN/Infinity, but these are not physical measurements.
        raw = values.get("value", "")
        try:
            number = Decimal(str(raw).replace(",", "."))
        except InvalidOperation:
            pass  # Text/boolean values remain subject to the model's typed validation.
        else:
            if not number.is_finite():
                raise ReferenceValidationFailed("Specification values must not be NaN or Infinity.")
    return create_reference(resource, CreateReferenceInput(values, idempotency_key), actor=actor)
