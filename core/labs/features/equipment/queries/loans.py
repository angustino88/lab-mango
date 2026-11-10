"""Read-only loan queries (redesign step 3)."""

from core.labs.models import EquipmentLoan


def get_active_loan(*, equipment_id: int) -> EquipmentLoan:
    """The unit's open loan with its borrower. Raises ``EquipmentLoan.DoesNotExist``. 1 query."""
    return EquipmentLoan.objects.select_related("borrower").get(
        equipment_id=equipment_id, equipment__deleted_at__isnull=True, returned_at__isnull=True
    )


__all__ = ("get_active_loan",)
