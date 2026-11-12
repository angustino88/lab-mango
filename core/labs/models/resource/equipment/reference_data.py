from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils.text import slugify
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.reference_data.models import ProtectedReferenceMixin


class EquipmentBase(TimeStampedModel, UserStampedModel):
    """Shared: active flag + validate on every save()."""

    active = models.BooleanField(default=True, db_index=True)

    class Meta:
        abstract = True

    def normalize(self) -> None:
        pass

    def save(self, *args, **kwargs):
        self.normalize()
        self.full_clean()
        return super().save(*args, **kwargs)


class EquipmentCategory(ProtectedReferenceMixin, EquipmentBase):
    name = models.CharField(max_length=120)
    key = models.SlugField(
        max_length=32,
        unique=True,
        null=True,
        blank=True,
        help_text=(
            "Stable code used by the code base (e.g. 'computing'). Filled from the name "
            "when empty. Renaming the category never changes it."
        ),
    )
    definition = models.TextField()
    # Capabilities checked by the equipment commands (redesign step 6).
    bookable = models.BooleanField(default=True, help_text="Units can be lent and reserved.")
    placeable_on_bench = models.BooleanField(default=True, help_text="Units can be assigned to a bench.")
    calibratable = models.BooleanField(default=True, help_text="Units may require calibration.")
    monitored = models.BooleanField(
        default=False,
        help_text="Units carry computing columns and may run the monitoring agent (ComputingProfile).",
    )

    class Meta:
        app_label = "labs"
        verbose_name_plural = "equipment categories"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(Lower("name"), name="equipment_category_name_uniq"),
        ]

    def __str__(self) -> str:
        return self.name

    def normalize(self):
        self.name = self.name.strip()
        self.definition = self.definition.strip()
        self.key = (self.key or slugify(self.name)).strip().lower()[:32]

    @property
    def effective_key(self) -> str:
        """The stable key, falling back to the slugified name for rows not migrated yet."""
        return self.key or slugify(self.name)


class EquipmentKind(EquipmentBase):
    category = models.ForeignKey(
        "labs.EquipmentCategory", related_name="kinds", on_delete=models.PROTECT
    )
    name = models.CharField(max_length=120)

    class Meta:
        app_label = "labs"
        ordering = ("category__name", "name")
        constraints = [
            models.UniqueConstraint(
                "category", Lower("name"), name="equipment_kind_category_name_uniq"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.category.name} / {self.name}"          # Computing / Laptop

    def normalize(self):
        self.name = self.name.strip()

    def clean(self):
        super().clean()
        if self.active and self.category_id and not self.category.active:
            raise ValidationError({"category": "Category is inactive."})


class EquipmentType(EquipmentBase):
    kind = models.ForeignKey(
        "labs.EquipmentKind", related_name="types", on_delete=models.PROTECT
    )
    name = models.CharField(max_length=120)

    class Meta:
        app_label = "labs"
        ordering = ("kind__category__name", "kind__name", "name")
        constraints = [
            models.UniqueConstraint(
                "kind", Lower("name"), name="equipment_type_kind_name_uniq"
            ),
        ]
        indexes = [
            GinIndex(fields=("name",), opclasses=["gin_trgm_ops"], name="equipment_type_name_trgm_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} / {self.name}"   # Computing / Laptop / Performance Laptop

    def normalize(self):
        self.name = self.name.strip()

    def clean(self):
        super().clean()
        if self.active and self.kind_id and not self.kind.active:
            raise ValidationError({"kind": "Kind is inactive."})


class EquipmentManufacturer(EquipmentBase):
    name = models.CharField(max_length=120)
    categories = models.ManyToManyField(
        "labs.EquipmentCategory", related_name="manufacturers", blank=True
    )

    class Meta:
        app_label = "labs"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(Lower("name"), name="equipment_manufacturer_name_uniq"),
        ]
        indexes = [
            GinIndex(fields=("name",), opclasses=["gin_trgm_ops"], name="equipment_mfr_name_trgm_idx"),
        ]

    def __str__(self) -> str:
        return self.name

    def normalize(self):
        self.name = self.name.strip()


class EquipmentProductModel(EquipmentBase):
    manufacturer = models.ForeignKey(
        "labs.EquipmentManufacturer", related_name="product_models", on_delete=models.PROTECT
    )
    equipment_type = models.ForeignKey(
        "labs.EquipmentType", related_name="product_models", on_delete=models.PROTECT
    )
    name = models.CharField(max_length=120)
    default_power_draw_w = models.PositiveIntegerField(
        null=True, blank=True, help_text="Copied to new assets of this model when empty."
    )
    default_weight_kg = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Copied to new assets of this model when empty.",
    )

    class Meta:
        app_label = "labs"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                "manufacturer", Lower("name"), name="equipment_product_model_mfr_name_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["equipment_type", "manufacturer"]),
            GinIndex(fields=("name",), opclasses=["gin_trgm_ops"], name="equipment_model_name_trgm_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.manufacturer.name} {self.name}"

    def normalize(self):
        self.name = self.name.strip()

    def clean(self):
        super().clean()
        if not (self.manufacturer_id and self.equipment_type_id):
            return
        category = self.equipment_type.kind.category
        if not self.manufacturer.categories.filter(pk=category.pk).exists():
            raise ValidationError(
                {"manufacturer": f"{self.manufacturer} is not registered for {category}."}
            )
        if self.active and not (self.manufacturer.active and self.equipment_type.active):
            raise ValidationError("Manufacturer and type must be active.")
