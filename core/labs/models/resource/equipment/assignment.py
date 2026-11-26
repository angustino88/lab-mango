"""Where a piece of equipment is: on a bench, at a station, in a room, or at an untracked place.

One table holds every placement so PostgreSQL can guarantee one active placement per unit
(``one_active_bench_per_equipment``; the name predates non-bench placements and is kept so
existing error mapping keeps working). ``EquipmentAssignment.objects`` returns bench placements
only, which is what every pre-existing reader means by "assignment". New code that needs every
placement uses ``EquipmentAssignment.all_placements`` or the ``EquipmentPlacement`` proxy.
See docs/proposals/equipment-management-redesign.md, step 1.
"""

from typing import ClassVar

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import IntegerRangeField, RangeOperators
from django.db import models
from django.db.models import F, Q
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel

LOCATION_NOTE_MAX_LENGTH = 255


class RackFace(models.TextChoices):
    FRONT = "front", "Front"
    REAR = "rear", "Rear"


class Int4Range(models.Func):
    """SQL ``int4range(lower, upper, '[)')`` for exclusion constraints."""

    function = "INT4RANGE"
    output_field = IntegerRangeField()


class BenchPlacementManager(models.Manager):
    """Bench placements only: the historic meaning of an equipment assignment."""

    def get_queryset(self):
        return super().get_queryset().filter(bench__isnull=False)


class EquipmentAssignment(TimeStampedModel, UserStampedModel):
    bench = models.ForeignKey(
        "labs.Bench",
        related_name="equipment_assignments",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    station = models.ForeignKey(
        "labs.Station",
        related_name="equipment_placements",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    room = models.ForeignKey(
        "labs.Room",
        related_name="equipment_placements",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    location_note = models.CharField(
        max_length=LOCATION_NOTE_MAX_LENGTH,
        blank=True,
        default="",
        help_text="Required when no bench, station or room is set; otherwise an optional detail such as a shelf.",
    )
    equipment = models.ForeignKey(
        "labs.Equipment",
        related_name="bench_assignments",
        on_delete=models.PROTECT,
    )
    role = models.CharField(max_length=64, default="default")
    position = models.PositiveIntegerField(
        default=0,
        help_text="Display order of this equipment assignment within the bench; lower values appear first.",
    )
    monitor = models.BooleanField(default=False)
    # Rack-mounted equipment at a station: lowest occupied unit (1 = bottom), height in units, mounting face.
    rack_unit = models.PositiveSmallIntegerField(null=True, blank=True)
    rack_unit_height = models.PositiveSmallIntegerField(null=True, blank=True)
    rack_face = models.CharField(max_length=8, choices=RackFace.choices, blank=True, default="")
    assigned_at = models.DateTimeField()
    unassigned_at = models.DateTimeField(null=True, blank=True)

    objects: ClassVar[models.Manager] = BenchPlacementManager()
    all_placements: ClassVar[models.Manager] = models.Manager()

    @property
    def computer(self):
        return self.equipment

    @computer.setter
    def computer(self, val):
        self.equipment = val

    @property
    def target_type(self) -> str:
        if self.bench_id is not None:
            return "bench"
        if self.station_id is not None:
            return "station"
        if self.room_id is not None:
            return "room"
        return "note"

    class Meta:
        app_label = "labs"
        default_manager_name = "objects"
        base_manager_name = "all_placements"
        constraints = [
            models.UniqueConstraint(
                fields=("equipment",),
                condition=Q(unassigned_at__isnull=True),
                name="one_active_bench_per_equipment",
            ),
            models.CheckConstraint(
                condition=(
                    Q(unassigned_at__isnull=True)
                    | Q(unassigned_at__gte=F("assigned_at"))
                ),
                name="assignment_end_after_start",
            ),
            models.CheckConstraint(
                condition=(
                    Q(bench__isnull=False, station__isnull=True, room__isnull=True)
                    | Q(bench__isnull=True, station__isnull=False, room__isnull=True)
                    | Q(bench__isnull=True, station__isnull=True, room__isnull=False)
                    | (Q(bench__isnull=True, station__isnull=True, room__isnull=True) & ~Q(location_note=""))
                ),
                name="equipment_placement_one_target",
            ),
            models.CheckConstraint(
                condition=(Q(bench__isnull=False) | Q(role="default", position=0, monitor=False)),
                name="equipment_placement_bench_fields",
            ),
            # Rack position: all three fields or none, only for station placements, within 1..60 U.
            models.CheckConstraint(
                condition=(
                    Q(rack_unit__isnull=True, rack_unit_height__isnull=True, rack_face="")
                    | Q(
                        station__isnull=False,
                        rack_unit__gte=1,
                        rack_unit_height__gte=1,
                        rack_unit_height__lte=60,
                        rack_face__in=RackFace.values,
                    )
                ),
                name="equipment_placement_rack_position",
            ),
            # Two active rack-mounted units never share a unit of the same station.
            ExclusionConstraint(
                name="equipment_placement_rack_no_overlap",
                expressions=[
                    ("station", RangeOperators.EQUAL),
                    (Int4Range("rack_unit", F("rack_unit") + F("rack_unit_height")), RangeOperators.OVERLAPS),
                ],
                condition=Q(unassigned_at__isnull=True, rack_unit__isnull=False),
            ),
        ]
        indexes = [
            models.Index(
                fields=("bench", "position"),
                condition=Q(unassigned_at__isnull=True),
                name="equipment_assign_bench_idx",
            ),
        ]


class EquipmentPlacement(EquipmentAssignment):
    """Every placement (bench, station, room, untracked place); same table as ``EquipmentAssignment``."""

    objects: ClassVar[models.Manager] = models.Manager()

    class Meta:
        proxy = True
        app_label = "labs"
        default_manager_name = "objects"
