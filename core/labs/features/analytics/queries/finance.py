"""Combine distinct source transactions, with exact Decimal arithmetic and no FX."""

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from datetime import timezone as datetime_timezone
from decimal import Decimal
from typing import Literal, TypeAlias, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.labs.features.expense.public import ExpenseCashFlowAggregate, aggregate_expense_cash_flow
from core.labs.features.procurement.public import aggregate_procurement_cash_flow

from ..exceptions import AnalyticsValidationError


class Money(TypedDict):
    amount: str
    currency: str


class CashFlowTotals(TypedDict):
    payments: Money
    refunds: Money
    net: Money
    transaction_count: int


Source = Literal["expense", "procurement"]
CashFlowRows: TypeAlias = tuple[
    tuple[Literal["expense"], tuple[ExpenseCashFlowAggregate, ...]],
    tuple[Literal["procurement"], tuple],
]


@dataclass
class _Totals:
    payments: Decimal = Decimal("0.00")
    refunds: Decimal = Decimal("0.00")
    transaction_count: int = 0

    def add(self, *, amount: Decimal, transaction_type: str, count: int) -> None:
        if transaction_type == "payment":
            self.payments += amount
        elif transaction_type == "refund":
            self.refunds -= amount
        else:
            raise AnalyticsValidationError("Unsupported cash-flow transaction type.")
        self.transaction_count += count

    def serialize(self, currency: str) -> CashFlowTotals:
        def money(amount: Decimal) -> Money:
            return {"amount": format(amount, ".2f"), "currency": currency}

        return {
            "payments": money(self.payments),
            "refunds": money(self.refunds),
            "net": money(self.payments + self.refunds),
            "transaction_count": self.transaction_count,
        }


def _next_month(value: date) -> date:
    return date(value.year + value.month // 12, value.month % 12 + 1, 1)


def _report(*, currency: str, start_month: date, end_month: date, timezone: str = "UTC") -> dict:
    """Inclusive calendar months, capped at 24 even for non-HTTP callers.

    Expense date-only values are already calendar dates, never shifted. Timestamp
    boundaries and procurement buckets are local midnights in the selected zone.
    Source transactions are assumed distinct: no reference-based deduplication.
    Procurement has no expense type and is deliberately classified separately.
    """
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise AnalyticsValidationError("An explicit uppercase three-letter currency is required.")
    months_count = (end_month.year - start_month.year) * 12 + end_month.month - start_month.month + 1
    if start_month.day != 1 or end_month.day != 1 or not 1 <= months_count <= 24:
        raise AnalyticsValidationError("Expected first-of-month dates spanning 1 to 24 calendar months.")
    if end_month >= date(9999, 12, 1):
        raise AnalyticsValidationError("End month must have a representable exclusive boundary.")
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise AnalyticsValidationError("Expected a valid IANA timezone.") from error
    exclusive_end = _next_month(end_month)
    try:
        start_at = datetime.combine(start_month, time.min, zone).astimezone(datetime_timezone.utc)
        end_at = datetime.combine(exclusive_end, time.min, zone).astimezone(datetime_timezone.utc)
    except OverflowError as error:
        raise AnalyticsValidationError("UTC calendar boundaries must be representable.") from error
    expense_rows = aggregate_expense_cash_flow(currency=currency, start_date=start_month, end_date=exclusive_end)
    procurement_rows = aggregate_procurement_cash_flow(
        currency=currency,
        start_at=start_at,
        end_at=end_at,
        reporting_timezone=zone,
    )
    combined = _Totals()
    sources: dict[Source, _Totals] = {"expense": _Totals(), "procurement": _Totals()}
    monthly: dict[date, dict[str, _Totals]] = {}
    month = start_month
    while month < exclusive_end:
        monthly[month] = {"combined": _Totals(), "expense": _Totals(), "procurement": _Totals()}
        month = _next_month(month)
    breakdown: dict[tuple[str, str], _Totals] = {}
    source_rows: CashFlowRows = (("expense", expense_rows), ("procurement", procurement_rows))
    for source, rows in source_rows:
        for row in rows:
            category = row.expense_type if isinstance(row, ExpenseCashFlowAggregate) else "procurement"
            key = (source, category)
            category_total = breakdown.setdefault(key, _Totals())
            source_total = sources[source]
            month_totals = monthly[row.month]
            monthly_source_total = month_totals[source]
            for target in (
                combined,
                source_total,
                month_totals["combined"],
                monthly_source_total,
                category_total,
            ):
                target.add(amount=row.amount, transaction_type=row.transaction_type, count=row.transaction_count)
    return {
        "currency": currency,
        "start_month": start_month.strftime("%Y-%m"),
        "end_month": end_month.strftime("%Y-%m"),
        "timezone": timezone,
        "period_start": start_at,
        "period_end": end_at,
        "combined": combined.serialize(currency),
        "sources": {source: total.serialize(currency) for source, total in sources.items()},
        "months": [
            {
                "month": month.strftime("%Y-%m"),
                "combined": totals["combined"].serialize(currency),
                "sources": {source: totals[source].serialize(currency) for source in sources},
            }
            for month, totals in monthly.items()
        ],
        "items": [
            {"source": source, "expense_type": category, **total.serialize(currency)}
            for (source, category), total in sorted(breakdown.items())
        ],
    }


def get_finance_summary(*, currency: str, start_month: date, end_month: date, timezone: str = "UTC") -> dict:
    report = _report(currency=currency, start_month=start_month, end_month=end_month, timezone=timezone)
    return {key: value for key, value in report.items() if key not in {"months", "items"}}


def get_finance_monthly_trends(*, currency: str, start_month: date, end_month: date, timezone: str = "UTC") -> dict:
    report = _report(currency=currency, start_month=start_month, end_month=end_month, timezone=timezone)
    return {key: value for key, value in report.items() if key != "items"}


def get_finance_breakdown(*, currency: str, start_month: date, end_month: date, timezone: str = "UTC") -> dict:
    report = _report(currency=currency, start_month=start_month, end_month=end_month, timezone=timezone)
    return {key: value for key, value in report.items() if key != "months"}


__all__ = ["get_finance_breakdown", "get_finance_monthly_trends", "get_finance_summary"]
