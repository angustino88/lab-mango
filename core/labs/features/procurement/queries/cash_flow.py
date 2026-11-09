"""Public procurement projection of settled transactions, not commitments."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Count, DecimalField, Sum
from django.db.models.functions import TruncMonth

from core.labs.models import PurchaseTransaction


@dataclass(frozen=True)
class ProcurementCashFlowAggregate:
    month: date
    transaction_type: str
    amount: Decimal
    transaction_count: int


def aggregate_procurement_cash_flow(
    *, currency: str, start_at: datetime, end_at: datetime, reporting_timezone: ZoneInfo
) -> tuple[ProcurementCashFlowAggregate, ...]:
    """Settled instants in [start_at, end_at), bucketed in reporting_timezone.

    Match the existing globally readable procurement collections. Purchase
    status/date, line items and allocations do not filter or join these totals.
    """
    rows = (
        PurchaseTransaction.objects.filter(
            purchase__currency=currency, settled_at__gte=start_at, settled_at__lt=end_at
        )
        .order_by()
        .annotate(month=TruncMonth("settled_at", tzinfo=reporting_timezone))
        .values("month", "transaction_type")
        .annotate(
            amount=Sum("amount", output_field=DecimalField(max_digits=28, decimal_places=2)),
            transaction_count=Count("pk"),
        )
        .order_by("month", "transaction_type")
    )
    return tuple(
        ProcurementCashFlowAggregate(
            month=row["month"].date(),
            transaction_type=row["transaction_type"],
            amount=row["amount"],
            transaction_count=row["transaction_count"],
        )
        for row in rows
    )


__all__ = ["ProcurementCashFlowAggregate", "aggregate_procurement_cash_flow"]
