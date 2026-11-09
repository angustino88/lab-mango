"""Billing building blocks shared by expenses, license agreements and purchases."""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class BillingPeriod(models.TextChoices):
    ONE_TIME = "one_time", _("One-time")
    MONTHLY = "monthly", _("Monthly")
    QUARTERLY = "quarterly", _("Quarterly")
    ANNUAL = "annual", _("Annual")


class PaymentTransactionType(models.TextChoices):
    PAYMENT = "payment", _("Payment")
    REFUND = "refund", _("Refund")


PERIODS_PER_YEAR = {
    BillingPeriod.MONTHLY: 12,
    BillingPeriod.QUARTERLY: 4,
    BillingPeriod.ANNUAL: 1,
}


def default_currency() -> str:
    """Single place for the default currency (override with LABS_DEFAULT_CURRENCY)."""
    return getattr(settings, "LABS_DEFAULT_CURRENCY", "EUR")


def validate_currency_code(value: str) -> None:
    if value and (len(value) != 3 or not value.isalpha() or not value.isupper()):
        raise ValidationError(_("Currency must be a three-letter upper-case code, e.g. EUR."))


def yearly_equivalent(amount: Decimal | None, billing_period: str) -> Decimal | None:
    """Amount per year for recurring costs; None for one-time costs."""
    if amount is None:
        return None
    periods = PERIODS_PER_YEAR.get(billing_period)
    return None if periods is None else amount * periods
