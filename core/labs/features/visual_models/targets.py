"""Resources that store a 3D model, and how each resolves the model it shows.

The visual_models feature owns the ``visual_model`` column on these tables: every read and write of it goes
through this feature. Catalog rows (station type, equipment category, product model) hold defaults that
items inherit when they have no model of their own.
"""

from collections.abc import Callable
from dataclasses import dataclass

from django.db.models import F, QuerySet, Value
from django.db.models.functions import Coalesce, Concat, NullIf

from core.labs.models import Bench, Equipment, Station
from core.labs.models.resource.equipment.reference_data import EquipmentCategory, EquipmentProductModel
from core.labs.models.resource.location.station import StationType


@dataclass(frozen=True)
class Target:
    segment: str  # URL collection the endpoint hangs off, e.g. "stations"
    label: str
    queryset: Callable[[], QuerySet]
    name: Callable[[], object]  # expression for the display name
    # Inherited defaults, nearest first: (source name, lookup of the default's visual_model_id).
    inherits: tuple[tuple[str, str], ...] = ()
    catalog: bool = False

    def effective(self):
        if not self.inherits:
            return F("visual_model_id")
        return Coalesce(F("visual_model_id"), *(F(lookup) for _, lookup in self.inherits))


TARGETS: dict[str, Target] = {
    target.segment: target
    for target in (
        Target(
            "station-types",
            "Station type",
            lambda: StationType.objects.all(),
            lambda: F("name"),
            catalog=True,
        ),
        Target(
            "equipment-categories",
            "Equipment category",
            lambda: EquipmentCategory.objects.all(),
            lambda: F("name"),
            catalog=True,
        ),
        Target(
            "equipment-product-models",
            "Product model",
            lambda: EquipmentProductModel.objects.all(),
            lambda: Concat(F("manufacturer__name"), Value(" "), F("name")),
            catalog=True,
        ),
        Target(
            "stations",
            "Station",
            lambda: Station.objects.all(),
            lambda: Coalesce(NullIf(F("name"), Value("")), F("sku")),
            inherits=(("station_type", "type__visual_model_id"),),
        ),
        Target(
            "benches", "Bench", lambda: Bench.objects.all(), lambda: Coalesce(NullIf(F("name"), Value("")), F("sku"))
        ),
        Target(
            "equipment",
            "Equipment",
            lambda: Equipment.objects.all(),
            lambda: Coalesce(NullIf(F("name"), Value("")), F("sku")),
            inherits=(
                ("product_model", "product_model__visual_model_id"),
                ("equipment_category", "kind__category__visual_model_id"),
            ),
        ),
    )
}
