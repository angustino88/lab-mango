"""Equipment-specific API foundation and persistence helpers."""

from core.labs.features.base import FeatureAPIView


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

    schema_tags = ("Equipment",)
