from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel


class LicenseAssignment(TimeStampedModel, UserStampedModel):
    license = models.ForeignKey(
        "labs.License",
        related_name="equipment_assignments",
        on_delete=models.PROTECT,
    )
    equipment = models.ForeignKey(
        "labs.Equipment",
        related_name="license_assignments",
        on_delete=models.PROTECT,
    )
    assigned_at = models.DateTimeField(default=timezone.now)
    unassigned_at = models.DateTimeField(null=True, blank=True)

    def clean(self) -> None:
        super().clean()
        if self.unassigned_at is not None or not self.license_id:
            return
        active = self.license.equipment_assignments.filter(unassigned_at__isnull=True)
        if self.pk:
            active = active.exclude(pk=self.pk)
        if active.count() >= self.license.seats:
            raise ValidationError({"license": "All seats of this license are already in use."})

    class Meta:
        app_label = "labs"
        constraints = [
            models.UniqueConstraint(
                fields=("license", "equipment"),
                condition=Q(unassigned_at__isnull=True),
                name="license_equipment_active_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(unassigned_at__isnull=True)
                    | Q(unassigned_at__gte=F("assigned_at"))
                ),
                name="license_assignment_end_after_start",
            ),
        ]
        indexes = [
            models.Index(
                fields=("license", "-assigned_at"),
                condition=Q(unassigned_at__isnull=True),
                name="license_assign_license_idx",
            ),
            models.Index(
                fields=("equipment", "-assigned_at"),
                condition=Q(unassigned_at__isnull=True),
                name="license_assign_equipment_idx",
            ),
        ]
