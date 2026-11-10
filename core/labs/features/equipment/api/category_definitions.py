"""Category HTTP field allowlists and reference-data definitions."""

from core.common.api.filtering import Filter, PositiveIDField
from core.labs.features.equipment.api.category_schema import EquipmentCategoryAPIConfig
from core.labs.features.equipment.api.registry import EQUIPMENT_REGISTRY
from core.labs.features.equipment.categories.computing.api import ComputingActivitySerializer
from core.labs.models.resource.equipment import (
    DisplayResolution,
    DisplaySize,
    EquipmentInterface,
    Material,
    NetworkingProtocol,
    SampleCharacteristic,
    SampleCustomer,
    TechnicalUser,
)

COMMON_EQUIPMENT_SEARCH_FIELDS = ("sku", "name", "serial_number", "log_label")

CATEGORY_DEFINITIONS = {
    "accessory": EquipmentCategoryAPIConfig(
        EQUIPMENT_REGISTRY["accessory"].model, searchable_fields=COMMON_EQUIPMENT_SEARCH_FIELDS
    ),
    "computing": EquipmentCategoryAPIConfig(
        EQUIPMENT_REGISTRY["computing"].model,
        fields=(
            "ip_address",
            "os_name",
            "disk_usage",
            "system_info",
            "monitored_devices",
            "rdp_file",
            "technical_user",
            "hostname",
            "mac_address",
        ),
        lookups=(("technical_users", TechnicalUser, "username"),),
        list_fields=("ip_address", "os_name", "mac_address"),
        # hostname is entered manually at registration (it names the RDP host); ip_address,
        # os_name and system_info stay agent-reported and are rejected on create.
        create_fields=("mac_address", "hostname"),
        update_fields=("monitored_devices", "technical_user"),
        searchable_fields=COMMON_EQUIPMENT_SEARCH_FIELDS + ("ip_address", "os_name", "hostname", "mac_address"),
        list_filters=(
            Filter(
                "technical_user_id", PositiveIDField(), "technical_user", "reference", options_key="technical_users"
            ),
        ),
        detail_relations=(("activity", ComputingActivitySerializer),),
    ),
    "debugging": EquipmentCategoryAPIConfig(
        EQUIPMENT_REGISTRY["debugging"].model, searchable_fields=COMMON_EQUIPMENT_SEARCH_FIELDS
    ),
    "display": EquipmentCategoryAPIConfig(
        EQUIPMENT_REGISTRY["display"].model,
        fields=("size", "resolution", "interfaces"),
        lookups=(
            ("sizes", DisplaySize, "size"),
            ("resolutions", DisplayResolution, "resolution"),
            ("interfaces", EquipmentInterface, "name"),
        ),
        searchable_fields=COMMON_EQUIPMENT_SEARCH_FIELDS
        + ("size__size", "resolution__resolution", "interfaces__name"),
        list_filters=(
            Filter("size_id", PositiveIDField(), "size", "reference", options_key="sizes"),
            Filter("resolution_id", PositiveIDField(), "resolution", "reference", options_key="resolutions"),
        ),
    ),
    "furniture": EquipmentCategoryAPIConfig(
        EQUIPMENT_REGISTRY["furniture"].model,
        fields=("dimensions", "material"),
        lookups=(("materials", Material, "name"),),
        searchable_fields=COMMON_EQUIPMENT_SEARCH_FIELDS + ("material__name",),
        list_filters=(Filter("material_id", PositiveIDField(), "material", "reference", options_key="materials"),),
    ),
    "instrument": EquipmentCategoryAPIConfig(
        EQUIPMENT_REGISTRY["instrument"].model,
        fields=("interfaces",),
        lookups=(("interfaces", EquipmentInterface, "name"),),
        searchable_fields=COMMON_EQUIPMENT_SEARCH_FIELDS + ("interfaces__name",),
    ),
    "laboratory": EquipmentCategoryAPIConfig(
        EQUIPMENT_REGISTRY["laboratory"].model, searchable_fields=COMMON_EQUIPMENT_SEARCH_FIELDS
    ),
    "mechanical": EquipmentCategoryAPIConfig(
        EQUIPMENT_REGISTRY["mechanical"].model,
        fields=("dimensions", "material"),
        lookups=(("materials", Material, "name"),),
        searchable_fields=COMMON_EQUIPMENT_SEARCH_FIELDS + ("material__name",),
        list_filters=(Filter("material_id", PositiveIDField(), "material", "reference", options_key="materials"),),
    ),
    "networking": EquipmentCategoryAPIConfig(
        EQUIPMENT_REGISTRY["networking"].model,
        fields=("protocol", "mac_address"),
        lookups=(("protocols", NetworkingProtocol, "name"),),
        searchable_fields=COMMON_EQUIPMENT_SEARCH_FIELDS + ("protocol__name", "mac_address"),
        list_filters=(Filter("protocol_id", PositiveIDField(), "protocol", "reference", options_key="protocols"),),
    ),
    "other": EquipmentCategoryAPIConfig(
        EQUIPMENT_REGISTRY["other"].model, searchable_fields=COMMON_EQUIPMENT_SEARCH_FIELDS
    ),
    "power": EquipmentCategoryAPIConfig(
        EQUIPMENT_REGISTRY["power"].model,
        fields=("channels", "interface", "power_rating"),
        lookups=(("interfaces", EquipmentInterface, "name"),),
        searchable_fields=COMMON_EQUIPMENT_SEARCH_FIELDS + ("interface__name",),
        list_filters=(Filter("interface_id", PositiveIDField(), "interface", "reference", options_key="interfaces"),),
    ),
    "sample": EquipmentCategoryAPIConfig(
        EQUIPMENT_REGISTRY["sample"].model,
        fields=("customer", "interfaces", "characteristics"),
        lookups=(
            ("customers", SampleCustomer, "name"),
            ("interfaces", EquipmentInterface, "name"),
            ("characteristics", SampleCharacteristic, "name"),
        ),
        searchable_fields=COMMON_EQUIPMENT_SEARCH_FIELDS
        + ("customer__name", "interfaces__name", "characteristics__name"),
        list_filters=(Filter("customer_id", PositiveIDField(), "customer", "reference", options_key="customers"),),
    ),
}

__all__ = ("CATEGORY_DEFINITIONS", "COMMON_EQUIPMENT_SEARCH_FIELDS", "EquipmentCategoryAPIConfig")
