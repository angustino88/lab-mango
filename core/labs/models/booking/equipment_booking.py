from django.db import models

from .base import Booking, no_overlap_constraint


class EquipmentBooking(Booking):
    equipment = models.ForeignKey(
        "labs.Equipment",
        related_name="bookings",
        on_delete=models.PROTECT,
    )

    def __str__(self) -> str:
        return f"{self.booking_code}: {self.equipment}"

    class Meta(Booking.Meta):
        app_label = "labs"
        constraints = [
            *Booking.Meta.constraints,
            no_overlap_constraint(name="equipment_booking_no_overlap", resource_field="equipment"),
        ]
        indexes = [
            models.Index(
                fields=("equipment", "starts_at", "ends_at"),
                name="equipment_booking_schedule_idx",
            ),
            models.Index(
                fields=("equipment", "status", "approval_status"),
                name="equipment_booking_state_idx",
            ),
        ]
