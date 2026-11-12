from decimal import Decimal

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.finance.billing import (
    PaymentTransactionType,
    default_currency,
    validate_currency_code,
)
from core.labs.models.resource.base.generic_links import resource_root_model

PURCHASE_RESOURCE_MODELS = {
    ("labs", "bench"),
    ("labs", "equipment"),
    ("labs", "license"),
    ("labs", "station"),
}


class PurchaseStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    ORDERED = "ordered", _("Ordered")
    RECEIVED = "received", _("Received")
    CANCELLED = "cancelled", _("Cancelled")


class PurchasePriority(models.Model):
    """Admin-managed priority reference for purchase lines."""

    code = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=64)
    rank = models.PositiveSmallIntegerField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "labs"
        verbose_name_plural = "purchase priorities"
        ordering = ("-rank", "id")
        constraints = [models.UniqueConstraint(Lower("name"), name="purchasepriority_name_ci_uniq")]

    def __str__(self) -> str:
        return self.name


class Purchase(TimeStampedModel, UserStampedModel):
    """A commercial purchase that may cover multiple equipment items."""

    supplier = models.CharField(max_length=255)
    purchase_order_number = models.CharField(max_length=100, blank=True, default="")
    purchase_date = models.DateField()
    currency = models.CharField(
        max_length=3,
        default=default_currency,
        validators=[validate_currency_code],
        help_text=_("ISO 4217 currency code."),
    )
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=_("Agreed total purchase amount."),
    )
    status = models.CharField(max_length=20, choices=PurchaseStatus.choices, default=PurchaseStatus.DRAFT)
    notes = models.TextField(blank=True, default="")
    version = models.PositiveIntegerField(default=1)

    @property
    def items_total(self) -> Decimal:
        """Sum of quantity x unit price of all lines (compare with ``total_amount``)."""
        return sum((item.quantity * item.unit_price for item in self.items.all()), Decimal("0.00"))

    @property
    def is_balanced(self) -> bool:
        return self.items_total == self.total_amount

    def __str__(self) -> str:
        return f"{self.purchase_order_number or self.pk} - {self.supplier}"

    class Meta:
        app_label = "labs"
        ordering = ("-purchase_date", "-id")
        indexes = [
            models.Index(fields=("purchase_date",), name="purchase_date_idx"),
            models.Index(fields=("status", "purchase_date"), name="purchase_status_date_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(total_amount__gte=0), name="purchase_total_nonnegative"),
        ]


class PurchaseItem(TimeStampedModel, UserStampedModel):
    purchase = models.ForeignKey(Purchase, related_name="items", on_delete=models.PROTECT)
    description = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    notes = models.TextField(blank=True, default="")
    purpose = models.TextField(null=True, blank=True)
    priority = models.ForeignKey(
        PurchasePriority,
        related_name="purchase_items",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    unit = models.CharField(max_length=32, null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        app_label = "labs"
        ordering = ("id",)
        indexes = [
            models.Index(fields=("purchase",), name="purchase_item_purchase_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=1), name="purchase_item_quantity_positive"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="purchase_item_price_nonnegative"),
        ]


class PurchaseItemResource(TimeStampedModel, UserStampedModel):
    """Allocates a purchase line's acquisition cost to one physical resource."""

    purchase_item = models.ForeignKey(
        PurchaseItem,
        related_name="resource_allocations",
        on_delete=models.PROTECT,
    )
    resource_type = models.ForeignKey(
        ContentType,
        related_name="purchase_item_resources",
        on_delete=models.PROTECT,
        limit_choices_to=Q(
            app_label__in={app for app, _ in PURCHASE_RESOURCE_MODELS},
            model__in={model for _, model in PURCHASE_RESOURCE_MODELS},
        ),
    )
    resource_id = models.PositiveBigIntegerField()
    resource = GenericForeignKey("resource_type", "resource_id")
    acquisition_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    def clean(self) -> None:
        super().clean()

        errors = {}
        if self.resource_type_id:
            model_label = (self.resource_type.app_label, self.resource_type.model)
            model = self.resource_type.model_class()
            if model_label not in PURCHASE_RESOURCE_MODELS:
                errors["resource_type"] = "This resource type cannot be allocated to a purchase item."
            elif model is not None and resource_root_model(model) is not model:
                errors["resource_type"] = "Use the root resource model (e.g. Equipment)."
            elif self.resource_id is not None and self.resource is None:
                errors["resource_id"] = "The referenced resource does not exist."

        if not self.purchase_item_id:
            if errors:
                raise ValidationError(errors)
            return

        allocations = PurchaseItemResource.objects.filter(purchase_item_id=self.purchase_item_id)
        if self.pk:
            allocations = allocations.exclude(pk=self.pk)

        allocation_count = allocations.count() + 1
        if allocation_count > self.purchase_item.quantity:
            errors["purchase_item"] = "Allocated resources exceed the purchase line quantity."

        allocated_value = sum(
            allocation.acquisition_price for allocation in allocations.only("acquisition_price")
        ) + self.acquisition_price
        line_value = self.purchase_item.quantity * self.purchase_item.unit_price
        if allocated_value > line_value:
            errors["acquisition_price"] = "Allocated acquisition cost exceeds the purchase line value."

        if errors:
            raise ValidationError(errors)

    class Meta:
        app_label = "labs"
        ordering = ("id",)
        indexes = [
            models.Index(
                fields=("resource_type", "resource_id"),
                name="purchase_item_resource_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("resource_type", "resource_id"),
                name="purchase_resource_unique",
            ),
            models.CheckConstraint(
                condition=Q(acquisition_price__gte=0),
                name="purchase_item_resource_price_nonnegative",
            ),
        ]


class PurchaseTransaction(TimeStampedModel, UserStampedModel):
    """A settled payment or refund associated with a purchase."""

    purchase = models.ForeignKey(Purchase, related_name="transactions", on_delete=models.PROTECT)
    transaction_type = models.CharField(max_length=10, choices=PaymentTransactionType.choices)
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    settled_at = models.DateTimeField()
    reference = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_("Invoice, receipt, bank transaction, or refund reference."),
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        app_label = "labs"
        ordering = ("-settled_at", "-id")
        indexes = [
            models.Index(fields=("purchase", "settled_at"), name="purchase_txn_purchase_idx"),
            models.Index(fields=("settled_at",), name="purchase_txn_settled_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="purchase_txn_amount_positive"),
        ]


class PurchaseIdempotencyRecord(models.Model):
    """Credential-scoped replay state for purchase create requests; never stores credentials."""

    credential_ref = models.CharField(max_length=128)
    key = models.CharField(max_length=64)
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=512)
    body_hash = models.CharField(max_length=64)
    state = models.CharField(max_length=16, choices=(("in_progress", "In progress"), ("completed", "Completed")))
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        app_label = "labs"
        constraints = [
            models.UniqueConstraint(fields=("credential_ref", "key"), name="purchase_idempotency_cred_key_uniq"),
            models.CheckConstraint(
                condition=Q(state="in_progress", status_code__isnull=True, response_body__isnull=True)
                | Q(state="completed", status_code__isnull=False, response_body__isnull=False),
                name="purchase_idempotency_state_result",
            ),
        ]
        indexes = [models.Index(fields=("expires_at",), name="purchase_idempotency_exp_idx")]


class PurchaseAuditEvent(models.Model):
    """Append-only, attributable record of each new draft mutation."""

    purchase = models.ForeignKey(Purchase, related_name="audit_events", on_delete=models.PROTECT)
    item_id = models.PositiveBigIntegerField(null=True, blank=True)
    action = models.CharField(max_length=8, choices=(("create", "Create"), ("update", "Update"), ("delete", "Delete")))
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="purchase_audit_events",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    credential_ref = models.CharField(max_length=128, null=True, blank=True)
    request_id = models.CharField(max_length=128)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "labs"
        ordering = ("occurred_at", "id")
        indexes = [
            models.Index(fields=("purchase", "occurred_at"), name="purchase_audit_time_idx"),
        ]
