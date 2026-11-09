"""Public expense cash-flow projection; obligations never participate in totals."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Count, DecimalField, Sum
from django.db.models.functions import TruncMonth

from core.labs.models import ExpensePayment


@dataclass(frozen=True)
class ExpenseCashFlowAggregate:
    month: date
    expense_type: str
    transaction_type: str
    amount: Decimal
    transaction_count: int


def aggregate_expense_cash_flow(
    *, currency: str, start_date: date, end_date: date
) -> tuple[ExpenseCashFlowAggregate, ...]:
    """Actual payments in [start_date, end_date); paid_at has no timezone.

    Scope matches existing globally readable finance reports. Only a many-to-one
    parent join is used, so other payments/resources cannot multiply amounts.
    """
    rows = (
        ExpensePayment.objects.filter(expense__currency=currency, paid_at__gte=start_date, paid_at__lt=end_date)
        .order_by()
        .annotate(month=TruncMonth("paid_at"))
        .values("month", "expense__expense_type", "transaction_type")
        .annotate(
            amount=Sum("amount", output_field=DecimalField(max_digits=28, decimal_places=2)),
            transaction_count=Count("pk"),
        )
        .order_by("month", "expense__expense_type", "transaction_type")
    )
    return tuple(
        ExpenseCashFlowAggregate(
            month=row["month"],
            expense_type=row["expense__expense_type"],
            transaction_type=row["transaction_type"],
            amount=row["amount"],
            transaction_count=row["transaction_count"],
        )
        for row in rows
    )


__all__ = ["ExpenseCashFlowAggregate", "aggregate_expense_cash_flow"]
