"""Pin removals of verified, repository-unreferenced Python compatibility aliases."""

from importlib import import_module

import pytest

REMOVED_MODULE_EXPORTS = (
    ("core.labs.models.resource.license.agreement", ("LicenseBillingPeriod",)),
    ("core.labs.models", ("LicenseBillingPeriod",)),
    ("core.labs.models.finance.expense", ("ExpenseBillingPeriod",)),
    ("core.labs.models.finance", ("ExpenseBillingPeriod",)),
    ("core.labs.models", ("ExpenseBillingPeriod", "PurchaseTransactionType")),
    ("core.labs.models.procurement.purchase", ("PurchaseTransactionType",)),
    ("core.labs.models.procurement", ("PurchaseTransactionType",)),
    (
        "core.labs.models.resource.equipment",
        (
            "DisplayInterface",
            "InstrumentInterface",
            "PowerInterface",
            "SampleInterface",
            "FurnitureMaterial",
            "MechanicalMaterial",
        ),
    ),
    (
        "core.labs.features.equipment.api.serializers",
        (
            "EquipmentChoicesQuerySerializer",
            "CategoryChoicesQuerySerializer",
            "EquipmentChoicesSerializer",
            "EquipmentSelectQuerySerializer",
            "CategorySelectQuerySerializer",
            "EquipmentSelectSerializer",
        ),
    ),
    (
        "core.labs.features.equipment.api.views",
        (
            "EquipmentChoicesAPIView",
            "EquipmentCategoryChoicesAPIView",
            "EquipmentSelectAPIView",
            "EquipmentCategorySelectAPIView",
        ),
    ),
    (
        "core.labs.features.equipment.queries.equipment",
        ("list_available_equipment", "category_available_equipment_queryset"),
    ),
    (
        "core.labs.features.equipment.queries",
        ("list_available_equipment", "category_available_equipment_queryset"),
    ),
    (
        "core.labs.features.monitoring.api.serializers",
        ("LabMonitoringSerializer", "LabMonitoringCreateSerializer"),
    ),
    ("core.labs.features.base.resource_filters", ("ResourceFilterMetadataMixin",)),
    ("core.infrastructure.storage.client", ("get_s3_client",)),
    ("core.labs.features.locations.api.serializers", ("StrictWriteMixin",)),
    ("core.common.openapi.api_catalog", ("build_endpoint_inventory",)),
    ("core.common.management.commands.spectacular_modules", ("ENDPOINT_INVENTORY_FILENAME",)),
    ("core.labs.features.base", ("ResourceChangeLogMixin",)),
)

REMOVED_MODULES = (
    "core.labs.models.booking.booking",
    "core.common.openapi.endpoint_inventory",
)

REMOVED_MODEL_ATTRIBUTES = (
    (
        "core.labs.models.activity.computing_activity",
        "ComputingActivity",
        ("Status", "OFFLINE", "computer", "computer_id", "remote_user_displayname", "inactive_time", "offline_time"),
    ),
    ("core.labs.models.finance.expense", "ExpensePayment", ("TransactionType",)),
    (
        "core.labs.models.booking.bench_booking",
        "BenchBooking",
        ("CANCEL", "EXPIRED", "from_date_time", "to_date_time", "lab_information", "lab_information_id"),
    ),
)


@pytest.mark.parametrize(("module_path", "names"), REMOVED_MODULE_EXPORTS)
def test_removed_python_aliases_are_not_exported(module_path: str, names: tuple[str, ...]) -> None:
    module = import_module(module_path)

    assert all(not hasattr(module, name) for name in names)


@pytest.mark.parametrize("module_path", REMOVED_MODULES)
def test_removed_compatibility_modules_cannot_be_imported(module_path: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        import_module(module_path)


@pytest.mark.parametrize(("module_path", "class_name", "names"), REMOVED_MODEL_ATTRIBUTES)
def test_removed_model_compatibility_attributes_are_not_present(
    module_path: str, class_name: str, names: tuple[str, ...]
) -> None:
    model = getattr(import_module(module_path), class_name)

    assert all(not hasattr(model, name) for name in names)
