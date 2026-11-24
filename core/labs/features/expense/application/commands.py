"""Expense and expense-payment write commands."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction

from core.common.domain.money import check_currency
from core.labs.models import Bench, Equipment, Expense, ExpensePayment, License, Room, Station
from core.labs.models.finance.expense import EXPENSE_RESOURCE_MODELS

EXPENSE_RESOURCE_KIND_MODELS = {
    "room": Room,
    "station": Station,
    "bench": Bench,
    "equipment": Equipment,
    "license": License,
}


@dataclass(frozen=True)
class CreateExpenseInput:
    name: str
    expense_type: str
    amount: Decimal
    valid_from: date
    resource_kind: str = "room"
    resource_id: int | None = None
    room_id: int | None = None
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
    currency: str | None = None  # the submitted money's currency; must be the expense's (FMT-2)


def _resolve_target_resource(command: CreateExpenseInput):
    if command.room_id is not None:
        if command.resource_id is not None and (command.resource_kind != "room" or command.resource_id != command.room_id):
            raise ValidationError({"resource_id": "Conflicting target resource identifiers."})
        resource_kind = "room"
        resource_id = command.room_id
    else:
        resource_kind = command.resource_kind
        resource_id = command.resource_id

    model = EXPENSE_RESOURCE_KIND_MODELS.get(resource_kind)
    if model is None:
        raise ValidationError({"resource_kind": "Unsupported resource kind."})
    if resource_id is None:
        raise ValidationError({"resource_id": "This field is required."})

    # Lock the target resource row so a concurrent soft-delete cannot slip in before commit.
    resource = model.objects.select_for_update().get(pk=resource_id, deleted_at__isnull=True)
    resource_type = ContentType.objects.get_for_model(model)
    if (resource_type.app_label, resource_type.model) not in EXPENSE_RESOURCE_MODELS:
        raise ValidationError({"resource_type": "This resource type cannot have expenses."})
    return resource_type, resource


@transaction.atomic
def create_expense(command: CreateExpenseInput, *, actor) -> Expense:
    resource_type, resource = _resolve_target_resource(command)
    expense = Expense(
        resource_type=resource_type,
        resource_id=resource.pk,
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
    check_currency(command.currency, expense.currency, field="total")
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
