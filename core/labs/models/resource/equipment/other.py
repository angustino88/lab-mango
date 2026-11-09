
from core.labs.models.resource.equipment.equipment import Equipment


class OtherEquipment(Equipment):
    """Equipment that does not fit another category."""

    EQUIPMENT_CATEGORY_KEY = "other"

    class Meta:
        app_label = "labs"
