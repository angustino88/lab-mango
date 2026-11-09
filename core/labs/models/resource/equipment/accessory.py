from core.labs.models.resource.equipment.equipment import Equipment


class AccessoryEquipment(Equipment):
    """Accessory equipment extension of the shared equipment record."""

    EQUIPMENT_CATEGORY_KEY = "accessory"

    class Meta:
        app_label = "labs"
