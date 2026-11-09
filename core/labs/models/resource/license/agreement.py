
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.finance.billing import BillingPeriod, default_currency, validate_currency_code


class LicenseAgreement(TimeStampedModel, UserStampedModel):
    """DEPRECATED: license fees are now Expense rows (expense_type=license_fee).

    Kept for one release so existing data can be copied into Expense; remove it
    (and LicensePayment) afterwards. See docs/MIGRATION_PLAN.md.
    """

    license = models.ForeignKey(
        "labs.License",
        related_name="agreements",
        on_delete=models.PROTECT,
    )
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=_("Amount charged per billing period."),
    )
    currency = models.CharField(max_length=3, default=default_currency, validators=[validate_currency_code])
    billing_period = models.CharField(
        max_length=20,
        choices=BillingPeriod.choices,
        default=BillingPeriod.ONE_TIME,
    )
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)

    class Meta:
        app_label = "labs"
        ordering = ("-valid_from", "-id")
        indexes = [
            models.Index(
                fields=("license", "valid_from"),
                name="license_agreement_start_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(valid_until__isnull=True)
                    | models.Q(valid_until__gte=models.F("valid_from"))
                ),
                name="license_agreement_valid_dates",
            ),
        ]
