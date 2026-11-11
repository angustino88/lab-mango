from typing import Final

from core.labs.models.resource.equipment.reference_data import EquipmentCategory
from core.reference_data.declarations import ReferenceList, ReferenceMode

_CATEGORY_NAMES: Final[tuple[str, ...]] = (
    "Accessory",
    "Computing",
    "Debugging",
    "Display",
    "Furniture",
    "Instrument",
    "Laboratory",
    "Mechanical",
    "Networking",
    "Other",
    "Power",
    "Sample",
)

REFERENCE_LISTS: Final[tuple[ReferenceList, ...]] = (
    ReferenceList(
        key="labs.equipment.categories",
        model=EquipmentCategory,
        identity="name",
        mode=ReferenceMode.ENSURE_PRESENT,
        rows=tuple(
            {
                "name": name,
                "definition": f"{name} equipment category.",
                "active": True,
                # Computing units carry a ComputingProfile and may run the monitoring agent.
                "monitored": name == "Computing",
            }
            for name in _CATEGORY_NAMES
        ),
    ),
)
