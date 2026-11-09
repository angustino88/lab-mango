from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.resource.base.resource import ResourceModel, ResourceStatusRecordModel


class NamedLookup(TimeStampedModel, UserStampedModel):
    """Required, unique, case-insensitive name. Base of the license lookup tables."""

    name = models.CharField(max_length=255)

    def clean(self) -> None:
        super().clean()
        self.name = (self.name or "").strip()
        if not self.name:
            raise ValidationError({"name": "A name is required."})

    def __str__(self) -> str:
        return self.name

    class Meta:
        abstract = True
        ordering = ("name",)


class LicenseVendor(NamedLookup):
    class Meta(NamedLookup.Meta):
        app_label = "labs"
        constraints = [models.UniqueConstraint(Lower("name"), name="license_vendor_name_uniq")]
        indexes = [GinIndex(fields=("name",), opclasses=("gin_trgm_ops",), name="license_vendor_name_idx")]


class LicenseProduct(NamedLookup):
    vendor = models.ForeignKey(
        "labs.LicenseVendor",
        related_name="products",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Vendor of the product; licenses must use the same vendor.",
    )

    class Meta(NamedLookup.Meta):
        app_label = "labs"
        constraints = [models.UniqueConstraint(Lower("name"), name="license_product_name_uniq")]
        indexes = [GinIndex(fields=("name",), opclasses=("gin_trgm_ops",), name="license_product_name_idx")]


class LicenseType(NamedLookup):
    class Meta(NamedLookup.Meta):
        app_label = "labs"
        constraints = [models.UniqueConstraint(Lower("name"), name="license_type_name_uniq")]
        indexes = [GinIndex(fields=("name",), opclasses=("gin_trgm_ops",), name="license_type_name_idx")]


class LicenseCategory(NamedLookup):
    class Meta(NamedLookup.Meta):
        app_label = "labs"
        verbose_name_plural = "License categories"
        constraints = [models.UniqueConstraint(Lower("name"), name="license_category_name_uniq")]
        indexes = [GinIndex(fields=("name",), opclasses=("gin_trgm_ops",), name="license_category_name_idx")]


class LicenseRestriction(NamedLookup):
    class Meta(NamedLookup.Meta):
        app_label = "labs"
        constraints = [models.UniqueConstraint(Lower("name"), name="license_restriction_name_uniq")]
        indexes = [GinIndex(fields=("name",), opclasses=("gin_trgm_ops",), name="license_restriction_name_idx")]


class License(ResourceModel):
    product = models.ForeignKey(
        "labs.LicenseProduct",
        related_name="licenses",
        on_delete=models.PROTECT,
    )
    vendor = models.ForeignKey(
        "labs.LicenseVendor",
        related_name="licenses",
        on_delete=models.PROTECT,
    )
    type = models.ForeignKey(
        "labs.LicenseType",
        related_name="licenses",
        on_delete=models.PROTECT,
    )
    category = models.ForeignKey(
        "labs.LicenseCategory",
        related_name="licenses",
        on_delete=models.PROTECT,
    )
    restriction = models.ForeignKey(
        "labs.LicenseRestriction",
        related_name="licenses",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    max_version = models.CharField(max_length=255, blank=True, default="")
    identifier = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="License key or serial. Secret: never log or export it.",
    )
    expiry_date = models.DateTimeField(null=True, blank=True)
    seats = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="How many assets may use the license at the same time.",
    )

    def clean(self) -> None:
        super().clean()
        if self.product_id and self.vendor_id:
            product_vendor_id = self.product.vendor_id
            if product_vendor_id and product_vendor_id != self.vendor_id:
                raise ValidationError({"vendor": "The vendor does not match the product's vendor."})

    @property
    def seats_in_use(self) -> int:
        return self.equipment_assignments.filter(unassigned_at__isnull=True).count()

    class Meta:
        app_label = "labs"
        constraints = ResourceModel.Meta.constraints
        indexes = [
            models.Index(fields=("product", "deleted_at"), name="license_product_deleted_idx"),
            models.Index(fields=("expiry_date",), name="license_expiry_idx"),
        ]


class LicenseStatus(models.TextChoices):
    AVAILABLE = "available", _("Available")
    ASSIGNED = "assigned", _("Assigned")
    EXPIRED = "expired", _("Expired")
    REVOKED = "revoked", _("Revoked")
    SUSPENDED = "suspended", _("Suspended")


class LicenseStatusRecord(ResourceStatusRecordModel):
    license = models.ForeignKey(
        "labs.License",
        related_name="status_records",
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        max_length=255,
        choices=LicenseStatus.choices,
    )

    class Meta:
        app_label = "labs"
        ordering = ("-created", "-id")
        indexes = [
            models.Index(fields=("license", "-created", "-id"), name="license_status_latest_idx"),
        ]
