"""Read-only expense collection and financial reporting queries."""
from __future__ import annotations

from collections import defaultdict
from datetime import date as Date
from decimal import Decimal

from django.db.models import QuerySet
from django.utils import timezone

from core.labs.models import Expense, ExpensePayment, PaymentTransactionType, Room


def list_room_expenses(*, room_id: int) -> QuerySet[Expense]:
    # Raises Room.DoesNotExist (mapped to 404) when the room is missing.
    Room.objects.get(pk=room_id)
    return (
        Expense.objects.filter(
            resource_type__app_label="labs",
            resource_type__model="room",
            resource_id=room_id,
        )
        .prefetch_related("resource")
        .order_by("-valid_from", "pk")
    )


def list_expense_payments(*, expense_id: int) -> QuerySet[ExpensePayment]:
    Expense.objects.get(pk=expense_id)
    # `total.currency` is the expense's: join it once, not once per payment (PRF-1).
    return ExpensePayment.objects.filter(expense_id=expense_id).select_related("expense").order_by("-paid_at", "pk")


def get_financial_report(
    *,
    room_id: int | None = None,
    expense_type: str | None = None,
    billing_period: str | None = None,
    status: str | None = None,
    from_date: Date | str | None = None,
    to_date: Date | str | None = None,
    currency: str = "EUR",
) -> dict:
    """Generate a comprehensive financial report with derived payment statuses and metrics."""
    if room_id is not None:
        Room.objects.get(pk=room_id)

    expenses_qs = Expense.objects.select_related("resource_type").prefetch_related("payments")

    if room_id is not None:
        expenses_qs = expenses_qs.filter(
            resource_type__app_label="labs",
            resource_type__model="room",
            resource_id=room_id,
        )

    if currency:
        expenses_qs = expenses_qs.filter(currency=currency)
    if expense_type:
        expenses_qs = expenses_qs.filter(expense_type=expense_type)
    if billing_period:
        expenses_qs = expenses_qs.filter(billing_period=billing_period)
    if from_date:
        expenses_qs = expenses_qs.filter(valid_from__gte=from_date)
    if to_date:
        expenses_qs = expenses_qs.filter(valid_from__lte=to_date)

    expenses = list(expenses_qs.order_by("-valid_from", "pk"))

    # Map room ids to room names
    room_ids = {e.resource_id for e in expenses if e.resource_type and e.resource_type.model == "room"}
    rooms_by_id = {r.id: r.name for r in Room.objects.filter(id__in=room_ids)}

    today = timezone.now().date()
    items = []
    total_refund_amount = Decimal("0.00")
    total_payment_count = 0

    for expense in expenses:
        payments = list(expense.payments.all())
        total_payment_count += len(payments)

        paid_sum = Decimal("0.00")
        refund_sum = Decimal("0.00")
        for p in payments:
            if p.transaction_type == PaymentTransactionType.REFUND:
                refund_sum += p.amount
            else:
                paid_sum += p.amount

        total_refund_amount += refund_sum
        net_paid = max(paid_sum - refund_sum, Decimal("0.00"))
        pending_amount = max(expense.amount - net_paid, Decimal("0.00"))

        if net_paid >= expense.amount:
            payment_status = "paid"
        elif net_paid > Decimal("0.00"):
            payment_status = "partially_paid"
        elif expense.valid_until and expense.valid_until < today:
            payment_status = "overdue"
        else:
            payment_status = "unpaid"

        if status and payment_status != status:
            continue

        room_name = rooms_by_id.get(expense.resource_id, "")

        items.append({
            "id": expense.id,
            "name": expense.name,
            "expense_type": expense.expense_type,
            "amount": expense.amount,
            "paid_amount": net_paid,
            "pending_amount": pending_amount,
            "payment_status": payment_status,
            "currency": expense.currency,
            "billing_period": expense.billing_period,
            "supplier": expense.supplier,
            "reference": expense.reference,
            "valid_from": expense.valid_from,
            "valid_until": expense.valid_until,
            "room_id": expense.resource_id,
            "room_name": room_name,
        })

    total_budgeted = sum((item["amount"] for item in items), Decimal("0.00"))
    total_paid = sum((item["paid_amount"] for item in items), Decimal("0.00"))
    total_pending = sum((item["pending_amount"] for item in items), Decimal("0.00"))

    # Breakdowns
    type_map = defaultdict(lambda: {"count": 0, "amount": Decimal("0.00"), "paid_amount": Decimal("0.00"), "pending_amount": Decimal("0.00")})
    room_map = defaultdict(lambda: {"room_name": "", "count": 0, "amount": Decimal("0.00"), "paid_amount": Decimal("0.00"), "pending_amount": Decimal("0.00")})
    status_map = defaultdict(lambda: {"count": 0, "amount": Decimal("0.00")})
    period_map = defaultdict(lambda: {"count": 0, "amount": Decimal("0.00"), "paid_amount": Decimal("0.00")})

    for item in items:
        # By expense type
        t_entry = type_map[item["expense_type"]]
        t_entry["count"] += 1
        t_entry["amount"] += item["amount"]
        t_entry["paid_amount"] += item["paid_amount"]
        t_entry["pending_amount"] += item["pending_amount"]

        # By room
        r_entry = room_map[item["room_id"]]
        r_entry["room_name"] = item["room_name"]
        r_entry["count"] += 1
        r_entry["amount"] += item["amount"]
        r_entry["paid_amount"] += item["paid_amount"]
        r_entry["pending_amount"] += item["pending_amount"]

        # By status
        s_entry = status_map[item["payment_status"]]
        s_entry["count"] += 1
        s_entry["amount"] += item["amount"]

        # By billing period
        p_entry = period_map[item["billing_period"]]
        p_entry["count"] += 1
        p_entry["amount"] += item["amount"]
        p_entry["paid_amount"] += item["paid_amount"]

    by_expense_type = [
        {"expense_type": k, **v} for k, v in sorted(type_map.items())
    ]
    by_room = [
        {"room_id": k, **v} for k, v in sorted(room_map.items())
    ]
    by_status = [
        {"status": k, **v} for k, v in sorted(status_map.items())
    ]
    by_billing_period = [
        {"billing_period": k, **v} for k, v in sorted(period_map.items())
    ]

    return {
        "currency": currency,
        "summary": {
            "total_budgeted": total_budgeted,
            "total_paid": total_paid,
            "total_pending": total_pending,
            "total_refunded": total_refund_amount,
            "expense_count": len(items),
            "payment_count": total_payment_count,
        },
        "by_expense_type": by_expense_type,
        "by_room": by_room,
        "by_status": by_status,
        "by_billing_period": by_billing_period,
        "items": items,
    }


__all__ = ["get_financial_report", "list_expense_payments", "list_room_expenses"]
