from core.labs.models.resource.equipment.equipment import Equipment


class DebuggingEquipment(Equipment):
    """Debugging equipment extension of the shared equipment record."""

    EQUIPMENT_CATEGORY_KEY = "debugging"

    class Meta:
        app_label = "labs"
