"""Technical specifications of a PRODUCT MODEL (entered once, shared by all its assets)."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.resource.equipment.reference_data import EquipmentBase

TRUE_VALUES = {"yes", "true", "1"}
FALSE_VALUES = {"no", "false", "0"}


class SpecificationDefinition(EquipmentBase):
    """Name, unit and type of a specification, e.g. 'Max Voltage' / V / number."""

    class ValueType(models.TextChoices):
        TEXT = "text", _("Text")
        NUMBER = "number", _("Number")
        BOOLEAN = "boolean", _("Yes / No")

    name = models.CharField(max_length=120)
    category = models.ForeignKey(
        "labs.EquipmentCategory",
        related_name="specification_definitions",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Category it mostly applies to; empty = any.",
    )
    unit = models.CharField(max_length=20, blank=True, default="")
    value_type = models.CharField(max_length=10, choices=ValueType.choices, default=ValueType.TEXT)

    class Meta:
        app_label = "labs"
        ordering = ("category__name", "name")
        constraints = [
            models.UniqueConstraint(Lower("name"), name="specification_definition_name_uniq"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.unit})" if self.unit else self.name

    def normalize(self):
        self.name = self.name.strip()
        self.unit = self.unit.strip()


class ProductModelSpecification(TimeStampedModel, UserStampedModel):
    """One specification value of a product model."""

    product_model = models.ForeignKey(
        "labs.EquipmentProductModel",
        related_name="specifications",
        on_delete=models.CASCADE,
    )
    definition = models.ForeignKey(
        "labs.SpecificationDefinition",
        related_name="values",
        on_delete=models.PROTECT,
    )
    value = models.CharField(max_length=255)

    def clean(self) -> None:
        super().clean()
        self.value = self.value.strip()
        if not self.value:
            raise ValidationError({"value": "A value is required."})
        if not self.definition_id:
            return
        kind = self.definition.value_type
        if kind == SpecificationDefinition.ValueType.NUMBER:
            try:
                Decimal(self.value.replace(",", "."))
            except InvalidOperation as error:
                raise ValidationError({"value": f"{self.definition.name} must be a number."}) from error
        elif kind == SpecificationDefinition.ValueType.BOOLEAN:
            if self.value.lower() not in TRUE_VALUES | FALSE_VALUES:
                raise ValidationError({"value": f"{self.definition.name} must be Yes or No."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        unit = f" {self.definition.unit}" if self.definition.unit else ""
        return f"{self.product_model}: {self.definition.name} = {self.value}{unit}"

    class Meta:
        app_label = "labs"
        ordering = ("product_model", "definition__name")
        constraints = [
            models.UniqueConstraint(
                fields=("product_model", "definition"),
                name="product_model_specification_uniq",
            ),
        ]
