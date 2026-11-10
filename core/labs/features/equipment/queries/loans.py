"""Read-only loan queries."""

from django.db.models import Q, QuerySet
from django.db.models.functions import Now

from core.labs.models import EquipmentLoan, EquipmentLoanBatch

_LOAN_JOINS = ("batch", "batch__borrower", "equipment")


def get_active_loan(*, equipment_id: int) -> EquipmentLoan:
    """The item's open loan with its batch and borrower. Raises ``EquipmentLoan.DoesNotExist``. 1 query."""
    return EquipmentLoan.objects.select_related(*_LOAN_JOINS).get(
        equipment_id=equipment_id, equipment__deleted_at__isnull=True, returned_at__isnull=True
    )


def list_loans(
    *,
    open: bool | None = None,  # noqa: A002 - mirrors the query parameter
    overdue: bool | None = None,
    borrower_id: int | None = None,
    borrower_name: str | None = None,
    equipment_id: int | None = None,
    batch_id: int | None = None,
) -> QuerySet[EquipmentLoan]:
    """Loan lines, newest first; joins only forward keys, so one row per loan. Page + count = 2 queries."""
    queryset = EquipmentLoan.objects.select_related(*_LOAN_JOINS).order_by("-handed_over_at", "-id")
    if open is not None:
        queryset = queryset.filter(returned_at__isnull=open)
    if overdue is not None:
        is_overdue = Q(returned_at__isnull=True, due_at__lt=Now())
        queryset = queryset.filter(is_overdue if overdue else ~is_overdue)
    if borrower_id is not None:
        queryset = queryset.filter(batch__borrower_id=borrower_id)
    if borrower_name:
        queryset = queryset.filter(
            Q(batch__borrower_name__icontains=borrower_name)
            | Q(batch__borrower__display_name__icontains=borrower_name)
            | Q(batch__borrower__username__icontains=borrower_name)
        )
    if equipment_id is not None:
        queryset = queryset.filter(equipment_id=equipment_id)
    if batch_id is not None:
        queryset = queryset.filter(batch_id=batch_id)
    return queryset


def get_loan_batch(*, batch_id: int) -> EquipmentLoanBatch:
    """One loan slip with its lines. 2 queries (batch, lines). Raises ``DoesNotExist``."""
    return (
        EquipmentLoanBatch.objects.select_related("borrower", "created_by")
        .prefetch_related("loans__equipment", "reservations__equipment")
        .get(pk=batch_id)
    )


__all__ = ("get_active_loan", "get_loan_batch", "list_loans")
