"""Telemetry reference data: what can be measured, and how to read a device model."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel


class MetricKind(models.TextChoices):
    GAUGE = "gauge", _("Gauge")
    COUNTER = "counter", _("Counter")


class MetricAggregation(models.TextChoices):
    MEAN = "mean", _("Mean")
    MIN = "min", _("Minimum")
    MAX = "max", _("Maximum")
    LAST = "last", _("Last value")
    DELTA = "delta", _("Delta (counters)")


class MetricCombination(models.TextChoices):
    SUM = "sum", _("Sum")
    MEAN = "mean", _("Mean")
    MAX = "max", _("Maximum")
    MIN = "min", _("Minimum")


class MetricDefinition(TimeStampedModel):
    """A measurable quantity with its unit and physically valid range.

    Reference data seeded by migration; a new metric is a new row, not a schema change. Counters
    (monotonic totals such as energy) always roll up as deltas. Never deleted while channels or
    readings use it (`PROTECT` from those tables). Owner: telemetry feature.
    """

    key = models.SlugField(max_length=64, primary_key=True, help_text="Stable code, e.g. temperature_c.")
    name = models.CharField(max_length=120)
    unit = models.CharField(max_length=32, help_text="Display unit, e.g. °C, %, W.")
    value_min = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    value_max = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    kind = models.CharField(max_length=16, choices=MetricKind.choices, default=MetricKind.GAUGE)
    aggregation = models.CharField(max_length=16, choices=MetricAggregation.choices, default=MetricAggregation.MEAN)
    combine = models.CharField(
        max_length=8,
        choices=MetricCombination.choices,
        default=MetricCombination.MEAN,
        help_text="How several channels of this metric on one target form the target's value (power: sum).",
    )
    decimals = models.PositiveSmallIntegerField(default=2)
    is_active = models.BooleanField(default=True)

    class Meta:
        app_label = "labs"
        ordering = ("key",)
        constraints = [
            models.CheckConstraint(
                condition=Q(value_min__isnull=True) | Q(value_max__isnull=True) | Q(value_min__lte=F("value_max")),
                name="telemetry_metric_range_ordered",
            ),
            models.CheckConstraint(
                condition=(Q(kind=MetricKind.COUNTER) & Q(aggregation=MetricAggregation.DELTA))
                | (Q(kind=MetricKind.GAUGE) & ~Q(aggregation=MetricAggregation.DELTA)),
                name="telemetry_metric_counter_uses_delta",
            ),
            models.CheckConstraint(condition=Q(decimals__lte=6), name="telemetry_metric_decimals_max"),
        ]

    def accepts(self, value: Decimal) -> bool:
        """True when `value` is inside the metric's physical range."""
        if self.value_min is not None and value < self.value_min:
            return False
        return self.value_max is None or value <= self.value_max

    def __str__(self) -> str:
        return f"{self.key} ({self.unit})"


class DeviceProtocol(models.TextChoices):
    MODBUS = "modbus", _("Modbus")


class DeviceProfileStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    APPROVED = "approved", _("Approved")


MODBUS_FUNCTION_CODES = frozenset({3, 4})
MODBUS_REGISTER_TYPES = {"int16": 1, "uint16": 1, "int32": 2, "uint32": 2, "float32": 2}
MODBUS_WORD_ORDERS = frozenset({"big", "little"})


def validate_modbus_read_map(read_map: Any) -> dict[str, str]:
    """Return field errors for a Modbus read map; empty when valid. Pure and deterministic."""
    if not isinstance(read_map, dict) or not read_map:
        return {"read_map": "Must be a non-empty object keyed by metric."}
    errors: dict[str, str] = {}
    for metric_key, entry in read_map.items():
        where = f"read_map.{metric_key}"
        if not isinstance(entry, dict):
            errors[where] = "Must be an object."
            continue
        register_type = entry.get("type")
        if entry.get("function_code") not in MODBUS_FUNCTION_CODES:
            errors[f"{where}.function_code"] = "Must be 3 (holding) or 4 (input)."
        register = entry.get("register")
        if not isinstance(register, int) or isinstance(register, bool) or not 0 <= register <= 65535:
            errors[f"{where}.register"] = "Must be an integer 0-65535."
        if register_type not in MODBUS_REGISTER_TYPES:
            errors[f"{where}.type"] = f"Must be one of {sorted(MODBUS_REGISTER_TYPES)}."
        elif entry.get("words", MODBUS_REGISTER_TYPES[register_type]) != MODBUS_REGISTER_TYPES[register_type]:
            errors[f"{where}.words"] = f"{register_type} uses {MODBUS_REGISTER_TYPES[register_type]} word(s)."
        if entry.get("word_order", "big") not in MODBUS_WORD_ORDERS:
            errors[f"{where}.word_order"] = "Must be big or little."
        for numeric in ("scale", "offset"):
            value = entry.get(numeric, 1 if numeric == "scale" else 0)
            if not isinstance(value, int | float) or isinstance(value, bool):
                errors[f"{where}.{numeric}"] = "Must be a number."
        if entry.get("scale") == 0:
            errors[f"{where}.scale"] = "Must not be zero."
    return errors


READ_MAP_VALIDATORS: dict[str, Callable[[Any], dict[str, str]]] = {
    DeviceProtocol.MODBUS.value: validate_modbus_read_map
}


class DeviceProfile(TimeStampedModel, UserStampedModel):
    """How to read one device model over one protocol, versioned.

    An edit is a new version (`key`, `version` unique); readings record the version they were decoded
    with. Only `approved` versions may be used by channels (application rule: approval requires a recorded
    bench test). Never deleted while channels use it (`PROTECT`). Owner: telemetry feature.
    """

    key = models.SlugField(max_length=64, help_text="Model code, e.g. chint_ddsu666.")
    version = models.PositiveIntegerField(default=1)
    protocol = models.CharField(max_length=16, choices=DeviceProtocol.choices)
    manufacturer = models.CharField(max_length=120, blank=True, default="")
    model = models.CharField(max_length=120, blank=True, default="")
    status = models.CharField(max_length=16, choices=DeviceProfileStatus.choices, default=DeviceProfileStatus.DRAFT)
    read_map = models.JSONField(
        default=dict, help_text="Per metric key, protocol-specific read instructions (validated per protocol)."
    )
    comm_defaults = models.JSONField(
        default=dict, blank=True, help_text="Informational defaults, e.g. serial settings from the manual."
    )
    notes = models.TextField(blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "labs"
        ordering = ("key", "-version")
        constraints = [
            models.UniqueConstraint(fields=["key", "version"], name="telemetry_profile_key_version_uniq"),
            models.CheckConstraint(condition=Q(version__gte=1), name="telemetry_profile_version_positive"),
            models.CheckConstraint(
                condition=Q(status=DeviceProfileStatus.DRAFT) | Q(approved_at__isnull=False),
                name="telemetry_profile_approved_has_time",
            ),
        ]

    @property
    def reference(self) -> str:
        """Stable label stored on readings, e.g. `chint_ddsu666@2`."""
        return f"{self.key}@{self.version}"

    def clean(self) -> None:
        super().clean()
        validator = READ_MAP_VALIDATORS.get(self.protocol)
        if validator is not None:
            errors = validator(self.read_map)
            if errors:
                raise ValidationError(errors)

    def __str__(self) -> str:
        return self.reference
