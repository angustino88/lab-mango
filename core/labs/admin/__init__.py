"""Labs Django admin, one module per functional area.

Importing the submodules registers their model admins. The admin index groups these models into
sections (``config/admin_site.py::ADMIN_SECTIONS``); keep that list in step when registering a model.
"""

from core.labs.admin import (  # noqa: F401  (imported for registration side effects)
    auditing,
    benches,
    bookings,
    equipment,
    licenses,
    locations,
    monitoring,
    organisation,
)
from core.labs.admin.equipment import (
    EquipmentCategoryAdmin,
    EquipmentKindAdmin,
    EquipmentManufacturerAdmin,
    EquipmentProductModelAdmin,
    EquipmentTypeAdmin,
)
from core.labs.admin.organisation import PurchasePriorityAdmin

__all__ = [
    "EquipmentCategoryAdmin",
    "EquipmentKindAdmin",
    "EquipmentManufacturerAdmin",
    "EquipmentProductModelAdmin",
    "EquipmentTypeAdmin",
    "PurchasePriorityAdmin",
]
