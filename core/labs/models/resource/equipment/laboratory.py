from core.labs.models.resource.equipment.equipment import Equipment


class LaboratoryEquipment(Equipment):
    """General laboratory equipment."""

    EQUIPMENT_CATEGORY_KEY = "laboratory"

    class Meta:
        app_label = "labs"
