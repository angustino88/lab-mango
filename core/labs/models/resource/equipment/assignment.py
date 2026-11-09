from django.db import models
from django.db.models import F, Q
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel


class EquipmentAssignment(TimeStampedModel, UserStampedModel):
    bench = models.ForeignKey(
        "labs.Bench",
        related_name="equipment_assignments",
        on_delete=models.PROTECT,
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
    assigned_at = models.DateTimeField()
    unassigned_at = models.DateTimeField(null=True, blank=True)

    @property
    def computer(self):
        return self.equipment

    @computer.setter
    def computer(self, val):
        self.equipment = val

    class Meta:
        app_label = "labs"
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
        ]
        indexes = [
            models.Index(
                fields=("bench", "position"),
                condition=Q(unassigned_at__isnull=True),
                name="equipment_assign_bench_idx",
            ),
        ]
