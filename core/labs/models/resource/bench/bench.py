from django.core.exceptions import ValidationError
from django.db import models

from core.labs.models.resource.base.resource import ResourceModel
from core.labs.models.resource.base.status import ResourceLifecycleStatus
from core.labs.models.resource.location.station_slot import StationSlotStatus


class Bench(ResourceModel):
    """A virtual test workspace optionally associated with a physical station.

    ResourceModel owns identity, ownership, images and timestamped deletion.
    EquipmentAssignment owns hardware placement; a bench does not create
    equipment, status or audit records when its setup location is read.
    """

    IMAGE_UPLOAD_FOLDER = "bench"

    # Bench is virtual. Lifecycle says whether the lab runs it (RS2 revisits OD3): "out of service" is
    # a downtime window (ResourceDowntime), and condition, availability and activity are computed,
    # never stored. Only an in-service, operational bench in an available station and room accepts bookings.
    LIFECYCLE_STATUSES = tuple(ResourceLifecycleStatus.choices)

    bench_group = models.ForeignKey(
        "labs.BenchGroup",
        related_name="benches",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Function of the bench (e.g. Radar, Video). The owning team is ResourceModel.group.",
    )
    description = models.TextField(blank=True, default="")
    documentation_url = models.URLField(max_length=500, blank=True, default="")
    type = models.ForeignKey(
        "labs.BenchType",
        related_name="benches",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    setup_location = models.ForeignKey(
        "labs.Station",
        related_name="configured_benches",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    station_slot = models.OneToOneField(
        "labs.StationSlot",
        related_name="bench",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    lifecycle_status = models.CharField(
        max_length=32,
        choices=LIFECYCLE_STATUSES,
        default=ResourceLifecycleStatus.IN_SERVICE,
    )
    criticality = models.CharField(max_length=32, blank=True, default="")
    requested_power_w = models.PositiveIntegerField(null=True, blank=True)
    requested_load_kg = models.PositiveIntegerField(null=True, blank=True)
    requested_cooling_w = models.PositiveIntegerField(null=True, blank=True)
    required_utilities = models.JSONField(default=dict, blank=True)
    commissioning_date = models.DateField(null=True, blank=True)
    # Deprecated: inspection history now lives in ResourceServiceRecord (kind=inspection).
    last_inspected_at = models.DateTimeField(null=True, blank=True)
    next_inspection_due_at = models.DateTimeField(null=True, blank=True)

    def clean(self) -> None:
        super().clean()
        self.criticality = self.criticality.strip()
        if self.station_slot_id is None:
            return
        if self.setup_location_id is None:
            raise ValidationError({
                "station_slot": "A bench must have a setup location before assigning a station slot."
            })
        if self.station_slot.station_id != self.setup_location_id:
            raise ValidationError({
                "station_slot": "The assigned slot must belong to the bench setup location."
            })
        if self.station_slot.status != StationSlotStatus.IN_SERVICE:
            raise ValidationError({"station_slot": "The assigned station slot is not available for bench placement."})
        if (
            self.type_id
            and self.station_slot.compatible_bench_types.exists()
            and not self.station_slot.compatible_bench_types.filter(pk=self.type_id).exists()
        ):
            raise ValidationError({"station_slot": "The assigned station slot is not compatible with this bench type."})
        if (
            self.requested_power_w is not None
            and self.station_slot.power_capacity_w is not None
            and self.requested_power_w > self.station_slot.power_capacity_w
        ):
            raise ValidationError({"requested_power_w": "Requested power exceeds station slot capacity."})
        if (
            self.requested_load_kg is not None
            and self.station_slot.max_load_kg is not None
            and self.requested_load_kg > self.station_slot.max_load_kg
        ):
            raise ValidationError({"requested_load_kg": "Requested load exceeds station slot capacity."})

    @property
    def setup_location_path(self) -> str:
        """Return the associated physical location path without becoming a location node."""
        if self.setup_location is None:
            return ""
        return self.setup_location.get_location_path()

    def __str__(self) -> str:
        return self.name or self.sku or "Unnamed bench"

    class Meta:
        app_label = "labs"
        verbose_name_plural = "benches"
        ordering = ("sku",)
        constraints = [
            *ResourceModel.Meta.constraints,
            models.CheckConstraint(
                condition=models.Q(lifecycle_status__in=ResourceLifecycleStatus.values),
                name="bench_lifecycle_valid",
            ),
        ]
        indexes = [
            models.Index(fields=("setup_location", "deleted_at"), name="bench_location_deleted_idx"),
            models.Index(fields=("bench_group", "deleted_at"), name="bench_group_deleted_idx"),
            models.Index(fields=("type", "deleted_at"), name="bench_type_deleted_idx"),
        ]
