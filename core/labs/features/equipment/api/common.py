"""Equipment-specific API foundation and persistence helpers."""

from rest_framework_api_key.permissions import HasAPIKey

from core.labs.features.base import FeatureAPIView
from core.users.public import IsLabCoordinator

# Reads: any authenticated user or API key. Writes: lab coordinators and administrators, or an API
# key (agents). Department scope (redesign OD9) is a later stage; this is the global role.
EQUIPMENT_PERMISSIONS = [HasAPIKey | IsLabCoordinator]


def sku_exists(sku: str, *, exclude_model=None, exclude_pk: int | None = None) -> bool:
    """Check normalized canonical SKUs; retain exclude_model for legacy callers."""
    from core.labs.models.resource.equipment.equipment import Equipment

    queryset = Equipment.objects.filter(sku=sku.strip(), deleted_at__isnull=True)
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    return queryset.exists()


def is_active_sku_unique_error(error) -> bool:
    """Recognize only the canonical equipment SKU constraint reported by PostgreSQL."""
    cause = error.__cause__ or error
    return getattr(getattr(cause, "diag", None), "constraint_name", None) == "equipment_active_sku_unique"


class EquipmentAPIView(FeatureAPIView):
    """Equipment specialization of the shared feature API foundation."""

    permission_classes = EQUIPMENT_PERMISSIONS
    schema_tags = ("Equipment",)
