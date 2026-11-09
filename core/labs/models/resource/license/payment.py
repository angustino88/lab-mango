from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.finance.billing import default_currency, validate_currency_code


class LicensePayment(TimeStampedModel, UserStampedModel):
    """DEPRECATED: use ExpensePayment on the license-fee Expense."""

    agreement = models.ForeignKey(
        "labs.LicenseAgreement",
        related_name="payments",
        on_delete=models.PROTECT,
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    currency = models.CharField(
        max_length=3,
        default=default_currency,
        validators=[validate_currency_code],
    )
    paid_at = models.DateField()
    reference = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    class Meta:
        app_label = "labs"
        ordering = ("-paid_at", "-id")
        indexes = [
            models.Index(
                fields=("paid_at",),
                name="license_payment_date_idx",
            ),
        ]
