"""Post-commit read-cache invalidation for Labs domain models.

Wired once in ``LabsConfig.ready()``. Model ``post_save`` / ``post_delete`` / ``m2m_changed``
signals bump the affected cache namespace generation inside ``transaction.on_commit(...)``,
so rolled-back writes never invalidate cached entries and committed ORM saves/deletes
invalidate stale reads immediately.

Paths that bypass Django model signals (``QuerySet.update()``, ``bulk_create()``,
``bulk_update()``) must call ``bump_namespace_version_on_commit(...)`` directly.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models.signals import m2m_changed, post_delete, post_save

from core.common.cache import bump_namespace_version_on_commit

EQUIPMENT_INVENTORY_CACHE_NS = "labs:equipment:inventory"
EQUIPMENT_REFDATA_CACHE_NS = "labs:equipment:refdata"
BENCHES_CACHE_NS = "labs:benches"
LOCATIONS_CACHE_NS = "labs:locations"
LICENSES_CACHE_NS = "labs:licenses"


def register_cache_invalidation() -> None:
    """Connect post-commit namespace invalidation signals for Labs models."""
    from core.labs.models import (
        Bench,
        BenchFavorite,
        BenchGroup,
        BenchType,
        Building,
        City,
        ComputingProfile,
        Country,
        Department,
        Equipment,
        EquipmentAssignment,
        EquipmentBooking,
        EquipmentCategory,
        EquipmentInterface,
        EquipmentKind,
        EquipmentLoan,
        EquipmentManufacturer,
        EquipmentProductModel,
        EquipmentType,
        Group,
        License,
        LicenseAgreement,
        LicenseAssignment,
        Material,
        ProductModelSpecification,
        PurchaseItemResource,
        ResourceDowntime,
        ResourceServiceRecord,
        Room,
        RoomSlot,
        SpecificationDefinition,
        Station,
        StationSlot,
        StationType,
        TechnicalUser,
    )
    from core.labs.models.resource.equipment import (
        DisplayResolution,
        DisplaySize,
        NetworkingProtocol,
        SampleCharacteristic,
        SampleCustomer,
    )

    model_namespaces: list[tuple[type[models.Model], tuple[str, ...]]] = [
        # Equipment inventory & live state
        (Equipment, (EQUIPMENT_INVENTORY_CACHE_NS,)),
        (ComputingProfile, (EQUIPMENT_INVENTORY_CACHE_NS,)),
        (EquipmentAssignment, (EQUIPMENT_INVENTORY_CACHE_NS, BENCHES_CACHE_NS, LOCATIONS_CACHE_NS)),
        (EquipmentLoan, (EQUIPMENT_INVENTORY_CACHE_NS,)),
        (EquipmentBooking, (EQUIPMENT_INVENTORY_CACHE_NS,)),
        (ResourceDowntime, (EQUIPMENT_INVENTORY_CACHE_NS, BENCHES_CACHE_NS, LOCATIONS_CACHE_NS)),
        (ResourceServiceRecord, (EQUIPMENT_INVENTORY_CACHE_NS,)),
        (PurchaseItemResource, (EQUIPMENT_INVENTORY_CACHE_NS, LICENSES_CACHE_NS)),
        # Equipment reference data (also invalidates inventory list projections that join names)
        (EquipmentCategory, (EQUIPMENT_REFDATA_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS)),
        (EquipmentKind, (EQUIPMENT_REFDATA_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS)),
        (EquipmentType, (EQUIPMENT_REFDATA_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS)),
        (EquipmentManufacturer, (EQUIPMENT_REFDATA_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS)),
        (EquipmentProductModel, (EQUIPMENT_REFDATA_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS)),
        (SpecificationDefinition, (EQUIPMENT_REFDATA_CACHE_NS,)),
        (ProductModelSpecification, (EQUIPMENT_REFDATA_CACHE_NS,)),
        (Department, (EQUIPMENT_REFDATA_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS, BENCHES_CACHE_NS)),
        (Group, (EQUIPMENT_REFDATA_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS, BENCHES_CACHE_NS)),
        (Material, (EQUIPMENT_REFDATA_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS)),
        (DisplaySize, (EQUIPMENT_REFDATA_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS)),
        (DisplayResolution, (EQUIPMENT_REFDATA_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS)),
        (NetworkingProtocol, (EQUIPMENT_REFDATA_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS)),
        (SampleCustomer, (EQUIPMENT_REFDATA_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS)),
        (EquipmentInterface, (EQUIPMENT_REFDATA_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS)),
        (SampleCharacteristic, (EQUIPMENT_REFDATA_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS)),
        (TechnicalUser, (EQUIPMENT_REFDATA_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS)),
        (get_user_model(), (EQUIPMENT_REFDATA_CACHE_NS,)),
        # Benches & locations
        (Bench, (BENCHES_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS)),
        (BenchFavorite, (BENCHES_CACHE_NS,)),
        (BenchType, (BENCHES_CACHE_NS,)),
        (BenchGroup, (BENCHES_CACHE_NS,)),
        (Room, (LOCATIONS_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS)),
        (RoomSlot, (LOCATIONS_CACHE_NS,)),
        (Station, (LOCATIONS_CACHE_NS, BENCHES_CACHE_NS, EQUIPMENT_INVENTORY_CACHE_NS)),
        (StationSlot, (LOCATIONS_CACHE_NS, BENCHES_CACHE_NS)),
        (StationType, (LOCATIONS_CACHE_NS,)),
        (Building, (LOCATIONS_CACHE_NS,)),
        (City, (LOCATIONS_CACHE_NS,)),
        (Country, (LOCATIONS_CACHE_NS,)),
        # Licenses
        (License, (LICENSES_CACHE_NS,)),
        (LicenseAssignment, (LICENSES_CACHE_NS,)),
        (LicenseAgreement, (LICENSES_CACHE_NS,)),
    ]

    for model, namespaces in model_namespaces:
        label = model._meta.label_lower

        def _make_handler(target_namespaces: tuple[str, ...]):
            def _handler(sender, **kwargs) -> None:
                bump_namespace_version_on_commit(*target_namespaces)

            return _handler

        handler = _make_handler(namespaces)
        post_save.connect(handler, sender=model, weak=False, dispatch_uid=f"labs_cache_save_{label}")
        post_delete.connect(handler, sender=model, weak=False, dispatch_uid=f"labs_cache_delete_{label}")

    def _on_equipment_m2m(sender, action: str, **kwargs) -> None:
        if action in {"post_add", "post_remove", "post_clear"}:
            bump_namespace_version_on_commit(EQUIPMENT_INVENTORY_CACHE_NS)

    m2m_changed.connect(
        _on_equipment_m2m,
        sender=Equipment.interfaces.through,
        weak=False,
        dispatch_uid="labs_cache_m2m_equipment_interfaces",
    )
    m2m_changed.connect(
        _on_equipment_m2m,
        sender=Equipment.characteristics.through,
        weak=False,
        dispatch_uid="labs_cache_m2m_equipment_characteristics",
    )


__all__ = [
    "BENCHES_CACHE_NS",
    "EQUIPMENT_INVENTORY_CACHE_NS",
    "EQUIPMENT_REFDATA_CACHE_NS",
    "LICENSES_CACHE_NS",
    "LOCATIONS_CACHE_NS",
    "register_cache_invalidation",
]
