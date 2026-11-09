"""Bounded calendar-month inputs and decimal-string cash-flow contracts."""

import re
from datetime import date
from datetime import timezone as datetime_timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from drf_api_contracts.serializers import ProblemDetailSerializer
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


@extend_schema_field({"type": "string", "pattern": r"^[0-9]{4}-(0[1-9]|1[0-2])$"})
class CalendarMonthField(serializers.DateField):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(input_formats=["%Y-%m"], **kwargs)

    def to_internal_value(self, data: Any) -> date:
        if not isinstance(data, str) or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", data):
            raise serializers.ValidationError("Expected a valid YYYY-MM calendar month.")
        return super().to_internal_value(data)


class FinanceQuerySerializer(serializers.Serializer):
    currency = serializers.RegexField(
        regex=r"^[A-Z]{3}$", max_length=3, help_text="Explicit three-letter currency; no FX conversion."
    )
    start_month = CalendarMonthField(help_text="Inclusive first calendar month (YYYY-MM).")
    end_month = CalendarMonthField(help_text="Inclusive last calendar month (YYYY-MM); maximum 24 months.")
    timezone = serializers.CharField(
        default="UTC",
        max_length=100,
        help_text="IANA zone for procurement timestamps and midnight boundaries. Expense paid_at dates are not shifted.",
    )

    def validate_timezone(self, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise serializers.ValidationError("Expected a valid IANA timezone.") from error
        return value

    def validate(self, attrs):
        start, end = attrs["start_month"], attrs["end_month"]
        count = (end.year - start.year) * 12 + end.month - start.month + 1
        if not 1 <= count <= 24:
            raise serializers.ValidationError({"end_month": "Window must span 1 to 24 calendar months."})
        if end >= date(9999, 12, 1):
            raise serializers.ValidationError({"end_month": "Exclusive next-month boundary must be representable."})
        return attrs


class FinanceMoneySerializer(serializers.Serializer):
    amount = serializers.RegexField(
        regex=r"^-?[0-9]+\.[0-9]{2}$", help_text="Exact decimal string, two source-stored decimal places."
    )
    currency = serializers.CharField()


class FinanceProblemResponseSerializer(serializers.Serializer):
    error = ProblemDetailSerializer()


class FinanceTotalsSerializer(serializers.Serializer):
    payments = FinanceMoneySerializer()
    refunds = FinanceMoneySerializer(help_text="Negative cash-flow contribution of refunds.")
    net = FinanceMoneySerializer(help_text="Payments plus signed refunds; may be negative.")
    transaction_count = serializers.IntegerField()


class FinanceSourcesSerializer(serializers.Serializer):
    expense = FinanceTotalsSerializer()
    procurement = FinanceTotalsSerializer()


class FinanceSummarySerializer(serializers.Serializer):
    currency = serializers.CharField()
    start_month = serializers.CharField()
    end_month = serializers.CharField()
    timezone = serializers.CharField()
    period_start = serializers.DateTimeField(
        default_timezone=datetime_timezone.utc,
        help_text="Inclusive instant at local first-month midnight, represented in UTC.",
    )
    period_end = serializers.DateTimeField(
        default_timezone=datetime_timezone.utc,
        help_text="Exclusive instant at local midnight following end_month, represented in UTC.",
    )
    combined = FinanceTotalsSerializer()
    sources = FinanceSourcesSerializer()


class FinanceMonthSerializer(serializers.Serializer):
    month = serializers.CharField()
    combined = FinanceTotalsSerializer()
    sources = FinanceSourcesSerializer()


class FinanceMonthlyTrendsSerializer(FinanceSummarySerializer):
    months = FinanceMonthSerializer(
        many=True, help_text="Chronological series, zero-filled for every requested month."
    )


class FinanceBreakdownItemSerializer(FinanceTotalsSerializer):
    expense_type = serializers.CharField(
        help_text="Expense-owned type, or procurement for purchases with no expense type."
    )

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["source"] = serializers.ChoiceField(choices=["expense", "procurement"])
        return fields


class FinanceBreakdownSerializer(FinanceSummarySerializer):
    items = FinanceBreakdownItemSerializer(many=True)


__all__ = [
    "FinanceBreakdownSerializer",
    "FinanceMonthlyTrendsSerializer",
    "FinanceQuerySerializer",
    "FinanceSummarySerializer",
]
