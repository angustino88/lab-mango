from decimal import Decimal

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.finance.billing import (
    BillingPeriod,
    PaymentTransactionType,
    default_currency,
    validate_currency_code,
    yearly_equivalent,
)
from core.labs.models.resource.base.generic_links import (
    resource_content_type,
    resource_content_types,
    resource_root_model,
)

# Resources that can carry costs. Always link the ROOT model (Equipment, not
# a subclass); use Expense.set_resource() to do that for you.
EXPENSE_RESOURCE_MODELS = {
    ("labs", "room"),
    ("labs", "station"),
    ("labs", "bench"),
    ("labs", "equipment"),
    ("labs", "license"),
}

class ExpenseType(models.TextChoices):
    RENT = "rent", _("Rent")
    UTILITIES = "utilities", _("Utilities")
    MAINTENANCE = "maintenance", _("Maintenance")
    CALIBRATION = "calibration", _("Calibration")
    REPAIR = "repair", _("Repair")
    SERVICE_CONTRACT = "service_contract", _("Service contract")
    LICENSE_FEE = "license_fee", _("License fee")
    INSURANCE = "insurance", _("Insurance")
    SERVICE = "service", _("Service (legacy)")
    OTHER = "other", _("Other")


class ExpenseQuerySet(models.QuerySet):
    def for_resource(self, resource: models.Model):
        if resource.pk is None:
            return self.none()
        return self.filter(
            resource_type__in=resource_content_types(resource),
            resource_id=resource.pk,
        )

    def recurring(self):
        return self.exclude(billing_period=BillingPeriod.ONE_TIME)


class Expense(TimeStampedModel, UserStampedModel):
    """A cost of a lab resource AFTER purchase: rent, calibration, repair, license fee ...

    `amount` is the agreed amount per billing period, or the total amount for a
    one-time expense. It is not the amount already paid (see ExpensePayment).
    The purchase price of an asset is NOT an expense: use Purchase.
    """

    resource_type = models.ForeignKey(
        ContentType,
        on_delete=models.PROTECT,
        related_name="expenses",
        limit_choices_to=Q(
            app_label__in={app for app, _ in EXPENSE_RESOURCE_MODELS},
            model__in={model for _, model in EXPENSE_RESOURCE_MODELS},
        ),
    )
    resource_id = models.PositiveBigIntegerField()
    resource = GenericForeignKey("resource_type", "resource_id")

    name = models.CharField(max_length=255)
    expense_type = models.CharField(max_length=20, choices=ExpenseType.choices)
    supplier = models.CharField(max_length=255, blank=True, default="")
    reference = models.CharField(max_length=255, blank=True, default="")

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    currency = models.CharField(max_length=3, default=default_currency, validators=[validate_currency_code])
    billing_period = models.CharField(
        max_length=20,
        choices=BillingPeriod.choices,
        default=BillingPeriod.ONE_TIME,
    )

    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    objects = ExpenseQuerySet.as_manager()

    def set_resource(self, resource: models.Model) -> None:
        """Link ``resource`` using its root content type."""
        self.resource_type = resource_content_type(resource)
        self.resource_id = resource.pk

    @property
    def yearly_amount(self):
        """Amount per year for recurring expenses; None when one-time."""
        return yearly_equivalent(self.amount, self.billing_period)

    def clean(self) -> None:
        super().clean()

        errors = {}

        if self.resource_type_id:
            model = self.resource_type.model_class()
            model_label = (self.resource_type.app_label, self.resource_type.model)

            if model_label not in EXPENSE_RESOURCE_MODELS:
                errors["resource_type"] = _("This resource type cannot have expenses.")
            elif model is not None and resource_root_model(model) is not model:
                errors["resource_type"] = _("Use the root resource model (e.g. Equipment).")
            elif self.resource_id is not None and self.resource is None:
                errors["resource_id"] = _("The referenced resource does not exist.")

        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            errors["valid_until"] = _("The end date must be on or after the start date.")

        if self.amount is not None and self.amount <= Decimal("0.00"):
            errors["amount"] = _("The amount must be greater than zero.")

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.name} ({self.amount} {self.currency})"

    class Meta:
        app_label = "labs"
        ordering = ("-valid_from", "-id")
        indexes = [
            models.Index(fields=("resource_type", "resource_id"), name="expense_resource_idx"),
            models.Index(fields=("resource_type", "expense_type"), name="expense_type_idx"),
            models.Index(fields=("currency", "billing_period"), name="expense_currency_period_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="expense_amount_positive"),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True) | Q(valid_until__gte=F("valid_from")),
                name="expense_valid_dates",
            ),
        ]


class ExpensePayment(TimeStampedModel, UserStampedModel):
    """Records an actual payment or refund against an expense.

    Amounts are always positive. `transaction_type` determines whether the
    transaction is a payment or a refund.
    """

    expense = models.ForeignKey(
        Expense,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    transaction_type = models.CharField(
        max_length=10,
        choices=PaymentTransactionType.choices,
        default=PaymentTransactionType.PAYMENT,
    )
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    paid_at = models.DateField()
    reference = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    def clean(self) -> None:
        super().clean()

        if self.amount is not None and self.amount <= Decimal("0.00"):
            raise ValidationError({"amount": _("The transaction amount must be greater than zero.")})

    class Meta:
        app_label = "labs"
        ordering = ("-paid_at", "-id")
        indexes = [
            models.Index(fields=("expense", "paid_at"), name="expense_payment_date_idx"),
            models.Index(fields=("expense", "transaction_type"), name="expense_payment_type_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="expense_payment_amount_positive"),
        ]
