from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.labs.models.resource.base.resource import ResourceModel

MAC_ADDRESS_VALIDATOR = RegexValidator(
    regex=r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$",
    message="Enter a MAC address like AA:BB:CC:DD:EE:FF.",
)


class EquipmentLifecycleState(models.TextChoices):
    """Whether the lab owns and runs the unit. Transitions: ``LIFECYCLE_TRANSITIONS``."""

    PLANNED = "planned", _("Planned")
    IN_SERVICE = "in_service", _("In service")
    TRANSFERRED_OUT = "transferred_out", _("Transferred out")
    RETIRED = "retired", _("Retired")
    LOST = "lost", _("Lost")


class EquipmentCondition(models.TextChoices):
    """Whether an in-service unit works. Any change is allowed while in service."""

    OPERATIONAL = "operational", _("Operational")
    IN_MAINTENANCE = "in_maintenance", _("In maintenance")
    OUT_OF_SERVICE = "out_of_service", _("Out of service")


class EquipmentDisplayStatus(models.TextChoices):
    """One read-only label computed from the stored facts; never written (redesign, display status)."""

    AVAILABLE = "available", _("Available")
    IN_USE = "in_use", _("In use")
    BORROWED = "borrowed", _("Borrowed")
    MAINTENANCE = "maintenance", _("Maintenance")
    BROKEN = "broken", _("Broken")
    CALIBRATION_OVERDUE = "calibration_overdue", _("Calibration overdue")
    ON_ORDER = "on_order", _("On order")
    TRANSFERRED = "transferred", _("Transferred")
    RETIRED = "retired", _("Retired")
    LOST = "lost", _("Lost")


LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    EquipmentLifecycleState.PLANNED: frozenset({EquipmentLifecycleState.IN_SERVICE, EquipmentLifecycleState.RETIRED}),
    EquipmentLifecycleState.IN_SERVICE: frozenset(
        {EquipmentLifecycleState.TRANSFERRED_OUT, EquipmentLifecycleState.RETIRED, EquipmentLifecycleState.LOST}
    ),
    EquipmentLifecycleState.LOST: frozenset({EquipmentLifecycleState.IN_SERVICE, EquipmentLifecycleState.RETIRED}),
    EquipmentLifecycleState.TRANSFERRED_OUT: frozenset({EquipmentLifecycleState.IN_SERVICE}),
    EquipmentLifecycleState.RETIRED: frozenset(),
}

# Entering one of these ends the lab's custody: no bench placement, other placements close.
GONE_LIFECYCLE_STATES = frozenset(
    {EquipmentLifecycleState.TRANSFERRED_OUT, EquipmentLifecycleState.RETIRED, EquipmentLifecycleState.LOST}
)


class Equipment(ResourceModel):
    """Shared record of every piece of equipment.

    Category-specific data lives in the subclasses (ComputingEquipment ...).
    Technical specifications of the model (channels, max voltage ...) live in
    ``ProductModelSpecification``; this table keeps only data that differs per unit.
    """

    EQUIPMENT_CATEGORY_KEY = "equipment"

    kind = models.ForeignKey(
        "labs.EquipmentKind",
        related_name="equipment",
        on_delete=models.PROTECT,
    )
    type = models.ForeignKey(
        "labs.EquipmentType",
        related_name="%(app_label)s_%(class)s_equipment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    manufacturer = models.ForeignKey(
        "labs.EquipmentManufacturer",
        related_name="%(app_label)s_%(class)s_equipment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    product_model = models.ForeignKey(
        "labs.EquipmentProductModel",
        related_name="%(app_label)s_%(class)s_equipment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    serial_number = models.CharField(max_length=255, blank=True, default="")
    firmware_version = models.CharField(
        max_length=255, blank=True, default="", help_text="Firmware currently installed on this unit."
    )
    log_label = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="previous / legacy label",
        help_text="Label that already existed on the asset before it was registered.",
    )
    licenses = models.ManyToManyField(
        "labs.License",
        through="labs.LicenseAssignment",
        related_name="equipment",
        blank=True,
    )
    details = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    lifecycle_state = models.CharField(
        max_length=32,
        choices=EquipmentLifecycleState.choices,
        default=EquipmentLifecycleState.IN_SERVICE,
        db_index=True,
        help_text="Changed only by the change_lifecycle command; history is in EquipmentEvent.",
    )
    condition = models.CharField(
        max_length=32,
        choices=EquipmentCondition.choices,
        default=EquipmentCondition.OPERATIONAL,
        db_index=True,
        help_text="Changed only by the change_condition command; operational unless in service.",
    )
    replacement_date = models.DateField(
        null=True,
        blank=True,
        help_text="Planned date when the equipment should be replaced.",
    )
    warranty_until = models.DateField(null=True, blank=True)
    power_draw_w = models.PositiveIntegerField(
        null=True, blank=True, help_text="Nameplate power consumption in watts."
    )
    weight_kg = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    calibration_required = models.BooleanField(
        default=False,
        help_text="History and due dates are kept as ResourceServiceRecord (kind=calibration).",
    )

    def apply_product_defaults(self) -> None:
        """Fill empty fields from the selected product model (only when still empty)."""
        if not self.product_model_id:
            return
        model = self.product_model
        if self.manufacturer_id is None:
            self.manufacturer_id = model.manufacturer_id
        if self.type_id is None:
            self.type_id = model.equipment_type_id
        if self.power_draw_w is None and model.default_power_draw_w is not None:
            self.power_draw_w = model.default_power_draw_w
        if self.weight_kg is None and model.default_weight_kg is not None:
            self.weight_kg = model.default_weight_kg

    def clean(self) -> None:
        super().clean()
        errors = {}
        if self.type_id and self.kind_id and self.type.kind_id != self.kind_id:
            errors["type"] = "The equipment type must belong to the selected kind."
        category_key = getattr(self, "EQUIPMENT_CATEGORY_KEY", None)
        if category_key and category_key != "equipment" and self.kind_id:
            if self.kind.category.effective_key != category_key:
                errors["kind"] = "The equipment kind must belong to the category."
        if self.product_model_id:
            model = self.product_model
            if self.manufacturer_id and model.manufacturer_id != self.manufacturer_id:
                errors["product_model"] = "The product model belongs to a different manufacturer."
            elif self.type_id and model.equipment_type_id != self.type_id:
                errors["product_model"] = "The product model belongs to a different equipment type."
            elif self.kind_id and model.equipment_type.kind_id != self.kind_id:
                errors["product_model"] = "The product model belongs to a different equipment kind."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.apply_product_defaults()
        return super().save(*args, **kwargs)

    @property
    def last_calibrated_at(self):
        # Equipment selectors annotate the latest calibration; None is a valid annotated value.
        if "latest_calibration_at" in self.__dict__:
            return self.__dict__["latest_calibration_at"]
        record = self.latest_service_record("calibration")
        return record.performed_at if record else None

    @property
    def next_calibration_due_at(self):
        if "latest_calibration_due_at" in self.__dict__:
            return self.__dict__["latest_calibration_due_at"]
        record = self.latest_service_record("calibration")
        return record.next_due_at if record else None

    @property
    def calibration_overdue(self) -> bool:
        due = self.next_calibration_due_at
        return bool(self.calibration_required and (due is None or due < timezone.now()))

    @property
    def image_upload_folder(self) -> str:
        return self.EQUIPMENT_CATEGORY_KEY

    class Meta:
        app_label = "labs"
        constraints = [
            models.UniqueConstraint(
                fields=("sku",), condition=models.Q(deleted_at__isnull=True),
                name="equipment_active_sku_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(lifecycle_state__in=EquipmentLifecycleState.values),
                name="equipment_lifecycle_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(condition__in=EquipmentCondition.values),
                name="equipment_condition_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(lifecycle_state=EquipmentLifecycleState.IN_SERVICE)
                | models.Q(condition=EquipmentCondition.OPERATIONAL),
                name="equipment_condition_only_in_service",
            ),
        ]
        indexes = [
            models.Index(fields=("kind", "deleted_at"), name="equipment_kind_deleted_idx"),
            models.Index(fields=("kind", "name"), name="equipment_kind_name_idx"),
        ]

    def __str__(self) -> str:
        return self.sku or self.name or str(self.pk)


class EquipmentEventAxis(models.TextChoices):
    LIFECYCLE = "lifecycle", _("Lifecycle")
    CONDITION = "condition", _("Condition")


class EquipmentEvent(models.Model):
    """Append-only history of lifecycle and condition changes; written only by the state commands."""

    equipment = models.ForeignKey("labs.Equipment", related_name="events", on_delete=models.PROTECT)
    axis = models.CharField(max_length=16, choices=EquipmentEventAxis.choices)
    from_value = models.CharField(max_length=32, blank=True, default="", help_text="Empty for the initial state.")
    to_value = models.CharField(max_length=32)
    reason = models.CharField(max_length=500, blank=True, default="")
    details = models.JSONField(
        default=dict, blank=True, help_text="Structured facts, e.g. receiving_organisation and transfer_date."
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="equipment_events", on_delete=models.SET_NULL
    )
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        app_label = "labs"
        ordering = ("occurred_at", "id")
        constraints = [
            models.CheckConstraint(condition=~models.Q(from_value=models.F("to_value")), name="equipment_event_changes"),
            models.CheckConstraint(
                condition=(
                    models.Q(axis="lifecycle", to_value__in=EquipmentLifecycleState.values)
                    | models.Q(axis="condition", to_value__in=EquipmentCondition.values)
                ),
                name="equipment_event_value_valid",
            ),
        ]
        indexes = [models.Index(fields=("equipment", "occurred_at", "id"), name="equipment_event_history_idx")]

    def __str__(self) -> str:
        return f"{self.equipment_id} {self.axis}: {self.from_value or '-'} -> {self.to_value}"
