from rest_framework import serializers

from core.common.api import AppModelSerializer
from core.labs.models import Expense, ExpensePayment, PaymentTransactionType


class ExpenseSerializer(AppModelSerializer):
    """Read and write shape for expenses. The room is taken from the URL, never the body."""

    expense_type = serializers.ChoiceField(choices=Expense._meta.get_field("expense_type").choices)
    billing_period = serializers.ChoiceField(
        choices=Expense._meta.get_field("billing_period").choices,
        required=False,
    )
    room = serializers.SerializerMethodField(read_only=True)
    amount_display = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Expense
        fields = (
            "id", "room", "name", "expense_type", "supplier", "reference", "amount", "currency",
            "amount_display", "billing_period", "valid_from", "valid_until", "notes",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def get_room(self, obj) -> dict[str, int | str]:
        return {"id": obj.resource_id, "name": getattr(obj.resource, "name", str(obj.resource_id))}

    def get_amount_display(self, obj) -> dict[str, str]:
        return {"amount": format(obj.amount, "f"), "currency": obj.currency}


class ExpensePaymentSerializer(AppModelSerializer):
    """Read and write shape for payments. The expense is taken from the URL, never the body."""

    transaction_type = serializers.ChoiceField(
        choices=PaymentTransactionType.choices,
        required=False,
    )

    class Meta:
        model = ExpensePayment
        fields = (
            "id", "transaction_type", "amount", "paid_at", "reference", "notes",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class FinancialReportQuerySerializer(serializers.Serializer):
    room_id = serializers.IntegerField(required=False)
    expense_type = serializers.CharField(required=False)
    billing_period = serializers.CharField(required=False)
    status = serializers.CharField(required=False)
    from_date = serializers.DateField(required=False)
    to_date = serializers.DateField(required=False)
    currency = serializers.CharField(required=False, default="EUR")


class FinancialReportSummarySerializer(serializers.Serializer):
    total_budgeted = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_paid = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_pending = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_refunded = serializers.DecimalField(max_digits=14, decimal_places=2)
    expense_count = serializers.IntegerField()
    payment_count = serializers.IntegerField()


class FinancialReportTypeBreakdownSerializer(serializers.Serializer):
    expense_type = serializers.CharField()
    count = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    paid_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    pending_amount = serializers.DecimalField(max_digits=14, decimal_places=2)


class FinancialReportRoomBreakdownSerializer(serializers.Serializer):
    room_id = serializers.IntegerField()
    room_name = serializers.CharField(allow_blank=True)
    count = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    paid_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    pending_amount = serializers.DecimalField(max_digits=14, decimal_places=2)


class FinancialReportStatusBreakdownSerializer(serializers.Serializer):
    status = serializers.CharField()
    count = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)


class FinancialReportPeriodBreakdownSerializer(serializers.Serializer):
    billing_period = serializers.CharField()
    count = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    paid_amount = serializers.DecimalField(max_digits=14, decimal_places=2)


class FinancialReportItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    expense_type = serializers.CharField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    paid_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    pending_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    payment_status = serializers.CharField()
    currency = serializers.CharField()
    billing_period = serializers.CharField()
    supplier = serializers.CharField(allow_blank=True)
    reference = serializers.CharField(allow_blank=True)
    valid_from = serializers.DateField()
    valid_until = serializers.DateField(allow_null=True)
    room_id = serializers.IntegerField()
    room_name = serializers.CharField(allow_blank=True)


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
    "ExpenseSerializer",
    "FinancialReportItemSerializer",
    "FinancialReportPeriodBreakdownSerializer",
    "FinancialReportQuerySerializer",
    "FinancialReportResponseSerializer",
    "FinancialReportRoomBreakdownSerializer",
    "FinancialReportStatusBreakdownSerializer",
    "FinancialReportSummarySerializer",
    "FinancialReportTypeBreakdownSerializer",
]
