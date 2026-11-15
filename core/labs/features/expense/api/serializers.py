from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api import AppModelSerializer
from core.common.api.money import MoneyField
from core.common.api.summary_serializers import ChoiceSerializer, choice_field, embedded_resource, to_choice
from core.labs.features.base.serializers import NamedReferenceSerializer
from core.labs.models import Expense, ExpensePayment, PaymentTransactionType

EXPENSE_TYPE_CHOICES = Expense._meta.get_field("expense_type").choices
BILLING_PERIOD_CHOICES = Expense._meta.get_field("billing_period").choices
PAYMENT_STATUS_CHOICES = [
    ("paid", "Paid"),
    ("partially_paid", "Partially paid"),
    ("overdue", "Overdue"),
    ("unpaid", "Unpaid"),
]


class ExpenseWriteSerializer(serializers.ModelSerializer):
    """Write shape for expenses (RW-1). The room is taken from the URL, never the body."""

    expense_type = serializers.ChoiceField(choices=EXPENSE_TYPE_CHOICES)
    billing_period = serializers.ChoiceField(choices=BILLING_PERIOD_CHOICES, required=False)
    start_date = serializers.DateField(source="valid_from")
    end_date = serializers.DateField(source="valid_until", required=False, allow_null=True)
    cost = MoneyField(min_value=0, help_text="What the expense costs (FMT-2, FMT-7).")

    class Meta:
        model = Expense
        fields = (
            "name", "expense_type", "supplier", "reference", "cost",
            "billing_period", "start_date", "end_date", "notes",
        )


class ExpenseSerializer(AppModelSerializer):
    """Read shape for expenses."""

    expense_type = choice_field(EXPENSE_TYPE_CHOICES)
    billing_period = choice_field(BILLING_PERIOD_CHOICES)
    start_date = serializers.DateField(source="valid_from", read_only=True)
    end_date = serializers.DateField(source="valid_until", read_only=True, allow_null=True)
    room = serializers.SerializerMethodField(read_only=True)
    cost = MoneyField(read_only=True)

    class Meta:
        model = Expense
        fields = (
            "id", "room", "name", "expense_type", "supplier", "reference", "cost",
            "billing_period", "start_date", "end_date", "notes",
            "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_room(self, obj) -> dict[str, int | str]:
        return {"id": obj.resource_id, "name": getattr(obj.resource, "name", str(obj.resource_id))}


class ExpensePaymentWriteSerializer(serializers.ModelSerializer):
    """Write shape for payments (RW-1). The expense is taken from the URL, never the body."""

    transaction_type = serializers.ChoiceField(choices=PaymentTransactionType.choices, required=False)
    paid_date = serializers.DateField(source="paid_at")
    total = MoneyField(currency="expense.currency", min_value=0, help_text="In the expense's currency.")

    class Meta:
        model = ExpensePayment
        fields = ("transaction_type", "total", "paid_date", "reference", "notes")


class ExpensePaymentSerializer(AppModelSerializer):
    """Read shape for payments; ``paid_date`` is a calendar date (NAM-3)."""

    transaction_type = choice_field(PaymentTransactionType.choices)
    paid_date = serializers.DateField(source="paid_at", read_only=True)
    total = MoneyField(currency="expense.currency", read_only=True)

    class Meta:
        model = ExpensePayment
        fields = (
            "id", "transaction_type", "total", "paid_date", "reference", "notes",
            "created_at", "updated_at",
        )
        read_only_fields = fields


class FinancialReportQuerySerializer(serializers.Serializer):
    room_id = serializers.IntegerField(required=False)
    expense_type = serializers.CharField(required=False)
    billing_period = serializers.CharField(required=False)
    status = serializers.CharField(required=False)
    from_date = serializers.DateField(required=False)
    to_date = serializers.DateField(required=False)
    currency = serializers.CharField(required=False, default="EUR")


def _report_currency(row, field) -> str:
    """Every amount of a financial report is in the report's currency."""
    return field.root.instance["currency"]


def _report_money(source: str) -> MoneyField:
    return MoneyField(amount=source, currency=_report_currency, read_only=True)


class FinancialReportSummarySerializer(serializers.Serializer):
    budgeted = _report_money("total_budgeted")
    paid = _report_money("total_paid")
    pending = _report_money("total_pending")
    refunded = _report_money("total_refunded")
    expense_count = serializers.IntegerField()
    payment_count = serializers.IntegerField()


class FinancialReportTypeBreakdownSerializer(serializers.Serializer):
    expense_type = serializers.SerializerMethodField()
    count = serializers.IntegerField()
    cost = _report_money("amount")
    paid = _report_money("paid_amount")
    pending = _report_money("pending_amount")


class FinancialReportRoomBreakdownSerializer(serializers.Serializer):
    room = serializers.SerializerMethodField()  # REL-14
    count = serializers.IntegerField()
    cost = _report_money("amount")
    paid = _report_money("paid_amount")
    pending = _report_money("pending_amount")


class FinancialReportStatusBreakdownSerializer(serializers.Serializer):
    status = serializers.SerializerMethodField()
    count = serializers.IntegerField()
    cost = _report_money("amount")


class FinancialReportPeriodBreakdownSerializer(serializers.Serializer):
    billing_period = serializers.SerializerMethodField()
    count = serializers.IntegerField()
    cost = _report_money("amount")
    paid = _report_money("paid_amount")


@embedded_resource
class FinancialReportItemSerializer(serializers.Serializer):
    """One expense row of the report (REL-15)."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    expense_type = serializers.SerializerMethodField()
    cost = _report_money("amount")
    paid = _report_money("paid_amount")
    pending = _report_money("pending_amount")
    payment_status = serializers.SerializerMethodField()
    billing_period = serializers.SerializerMethodField()
    supplier = serializers.CharField(allow_blank=True)
    reference = serializers.CharField(allow_blank=True)
    start_date = serializers.DateField(source="valid_from")
    end_date = serializers.DateField(source="valid_until", allow_null=True)
    room = serializers.SerializerMethodField()


def _room(row) -> dict:
    return {"id": row["room_id"], "name": row["room_name"] or f"Room {row['room_id']}"}


def _with_choice_getters(cls, **fields):
    """Add ``get_<field>`` methods rendering dict values as ENU-1 choices."""
    for field_name, (key, choices) in fields.items():

        @extend_schema_field(ChoiceSerializer)
        def getter(self, row, key=key, choices=choices) -> dict[str, str] | None:
            return to_choice(row[key], choices)

        setattr(cls, f"get_{field_name}", getter)
    return cls


@extend_schema_field(NamedReferenceSerializer)
def _get_room(self, row) -> dict:
    return _room(row)


_with_choice_getters(FinancialReportTypeBreakdownSerializer, expense_type=("expense_type", EXPENSE_TYPE_CHOICES))
_with_choice_getters(FinancialReportStatusBreakdownSerializer, status=("status", PAYMENT_STATUS_CHOICES))
_with_choice_getters(FinancialReportPeriodBreakdownSerializer, billing_period=("billing_period", BILLING_PERIOD_CHOICES))
_with_choice_getters(
    FinancialReportItemSerializer,
    expense_type=("expense_type", EXPENSE_TYPE_CHOICES),
    payment_status=("payment_status", PAYMENT_STATUS_CHOICES),
    billing_period=("billing_period", BILLING_PERIOD_CHOICES),
)
FinancialReportRoomBreakdownSerializer.get_room = _get_room
FinancialReportItemSerializer.get_room = _get_room


class FinancialReportResponseSerializer(serializers.Serializer):
    currency = serializers.CharField()
    summary = FinancialReportSummarySerializer()
    by_expense_type = serializers.ListField(child=FinancialReportTypeBreakdownSerializer())
    by_room = serializers.ListField(child=FinancialReportRoomBreakdownSerializer())
    by_status = serializers.ListField(child=FinancialReportStatusBreakdownSerializer())
    by_billing_period = serializers.ListField(child=FinancialReportPeriodBreakdownSerializer())
    items = serializers.ListField(child=FinancialReportItemSerializer())


__all__ = [
    "ExpensePaymentSerializer",
    "ExpensePaymentWriteSerializer",
    "ExpenseSerializer",
    "ExpenseWriteSerializer",
    "FinancialReportItemSerializer",
    "FinancialReportPeriodBreakdownSerializer",
    "FinancialReportQuerySerializer",
    "FinancialReportResponseSerializer",
    "FinancialReportRoomBreakdownSerializer",
    "FinancialReportStatusBreakdownSerializer",
    "FinancialReportSummarySerializer",
    "FinancialReportTypeBreakdownSerializer",
]
