"""Expense and expense-payment write commands."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction

from core.labs.models import Expense, ExpensePayment, Room
from core.labs.models.finance.expense import EXPENSE_RESOURCE_MODELS


@dataclass(frozen=True)
class CreateExpenseInput:
    room_id: int
    name: str
    expense_type: str
    amount: Decimal
    valid_from: date
    currency: str = "EUR"
    billing_period: str = "one_time"
    supplier: str = ""
    reference: str = ""
    valid_until: date | None = None
    notes: str = ""


@dataclass(frozen=True)
class CreateExpensePaymentInput:
    expense_id: int
    transaction_type: str
    amount: Decimal
    paid_at: date
    reference: str = ""
    notes: str = ""


@transaction.atomic
def create_expense(command: CreateExpenseInput, *, actor) -> Expense:
    room = Room.objects.get(pk=command.room_id)
    resource_type = ContentType.objects.get_for_model(Room)
    if (resource_type.app_label, resource_type.model) not in EXPENSE_RESOURCE_MODELS:
        raise ValidationError({"resource_type": "This resource type cannot have expenses."})
    expense = Expense(
        resource_type=resource_type,
        resource_id=room.pk,
        name=command.name,
        expense_type=command.expense_type,
        amount=command.amount,
        currency=command.currency,
        billing_period=command.billing_period,
        supplier=command.supplier,
        reference=command.reference,
        valid_from=command.valid_from,
        valid_until=command.valid_until,
        notes=command.notes,
        creator=actor,
        last_modified_by=actor,
    )
    expense.full_clean()
    expense.save(actor=actor)
    return expense


@transaction.atomic
def create_expense_payment(command: CreateExpensePaymentInput, *, actor) -> ExpensePayment:
    expense = Expense.objects.select_for_update().get(pk=command.expense_id)
    payment = ExpensePayment(
        expense=expense,
        transaction_type=command.transaction_type,
        amount=command.amount,
        paid_at=command.paid_at,
        reference=command.reference,
        notes=command.notes,
        creator=actor,
        last_modified_by=actor,
    )
    payment.full_clean()
    payment.save(actor=actor)
    return payment


__all__ = [
    "CreateExpenseInput",
    "CreateExpensePaymentInput",
    "create_expense",
    "create_expense_payment",
]
