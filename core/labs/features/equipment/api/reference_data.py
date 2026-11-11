"""Explicit equipment catalog import surface; no asset or credential writes."""

from core.common.api.reference_views import reference_urlpatterns
from core.labs.models.resource.base.resource import Department, ResourceGroup
from core.labs.models.resource.equipment.computing import TechnicalUser
from core.labs.models.resource.equipment.display import DisplayResolution, DisplaySize
from core.labs.models.resource.equipment.lookups import EquipmentInterface, Material
from core.labs.models.resource.equipment.networking import NetworkingProtocol
from core.labs.models.resource.equipment.reference_data import (
    EquipmentCategory,
    EquipmentKind,
    EquipmentManufacturer,
    EquipmentProductModel,
    EquipmentType,
)
from core.labs.models.resource.equipment.sample import SampleCharacteristic, SampleCustomer
from core.labs.models.resource.equipment.specification import ProductModelSpecification, SpecificationDefinition
from core.reference_data.contracts import ReferenceResource

from ..application.reference_data import create_catalog_reference
from ..queries.reference_data import get_catalog_reference, list_catalog_references

RESOURCES = (
    (
        "categories",
        EquipmentCategory,
        ("name", "key", "definition", "bookable", "placeable_on_bench", "calibratable", "monitored", "active"),
        ("name",),
        "name",
    ),
    ("kinds", EquipmentKind, ("name", "category", "active"), ("category_id", "name"), "name"),
    ("types", EquipmentType, ("name", "kind", "active"), ("kind_id", "name"), "name"),
    ("manufacturers", EquipmentManufacturer, ("name", "categories", "active"), ("name",), "name"),
    (
        "product-models",
        EquipmentProductModel,
        ("name", "manufacturer", "equipment_type", "default_power_draw_w", "default_weight_kg", "active"),
        ("manufacturer_id", "name"),
        "name",
    ),
    (
        "specification-definitions",
        SpecificationDefinition,
        ("name", "category", "unit", "value_type", "active"),
        ("name",),
        "name",
    ),
    (
        "product-model-specifications",
        ProductModelSpecification,
        ("product_model", "definition", "value"),
        ("product_model_id", "definition_id"),
        "value",
    ),
    ("interfaces", EquipmentInterface, ("name",), ("name",), "name"),
    ("materials", Material, ("name",), ("name",), "name"),
    ("display-sizes", DisplaySize, ("size", "diagonal_in"), ("size",), "size"),
    ("display-resolutions", DisplayResolution, ("resolution", "width_px", "height_px"), ("resolution",), "resolution"),
    ("networking-protocols", NetworkingProtocol, ("name",), ("name",), "name"),
    ("sample-customers", SampleCustomer, ("name",), ("name",), "name"),
    ("sample-characteristics", SampleCharacteristic, ("name",), ("name",), "name"),
    ("technical-users", TechnicalUser, ("username",), ("username",), "username"),
    ("departments", Department, ("name", "description", "active"), ("name",), "name"),
    ("resource-groups", ResourceGroup, ("name", "description", "department", "active"), ("name",), "name"),
)

urlpatterns = []
for segment, model, fields, identity, label in RESOURCES:
    urlpatterns += reference_urlpatterns(
        resource=ReferenceResource(f"equipment-reference-{segment}", model, fields, identity, label),
        prefix=f"equipment/reference-data/{segment}",
        tag="Equipment",
        module=__name__,
        create=create_catalog_reference,
        listing=list_catalog_references,
        retrieve=get_catalog_reference,
    )
