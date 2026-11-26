"""Seed the library with the built-in reference models and use them as catalog defaults.

Idempotent: identical bytes reuse the existing asset, and a default is only set on catalog rows that have no
model yet, so choices made by people are never overwritten.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from django.db import transaction

from core.labs.models.resource.equipment.reference_data import EquipmentCategory
from core.labs.models.resource.location.station import StationType

from ..contracts import AssetDetails, ModelStorage
from ..reference_models import REFERENCE_MODELS, build_glb
from . import store_asset
from .adapters import DjangoModelStorage

LICENSE = "Built-in LabMango reference model (original work, no third-party content)"

# Catalog name words → reference model key. Station types match the dashboard's station shapes.
STATION_TYPE_WORDS: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"rack", "racks"}), "server-rack"),
    (frozenset({"table", "desk", "bench", "workbench", "workstation"}), "lab-workbench"),
    (frozenset({"cabinet", "enclosure", "locker"}), "storage-cabinet"),
    (frozenset({"shelf", "shelves", "shelving"}), "storage-shelving"),
)
CATEGORY_WORDS: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"computing", "computer", "computers", "pc", "server", "servers", "workstation"}), "computer"),
    (frozenset({"display", "displays", "monitor", "monitors", "screen"}), "monitor"),
    (
        frozenset({"instrument", "instruments", "debugging", "measurement", "test", "laboratory", "power"}),
        "benchtop-instrument",
    ),
)


@dataclass
class SeedReport:
    created: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    station_types: list[str] = field(default_factory=list)
    equipment_categories: list[str] = field(default_factory=list)


def match_reference(name: str, words: Iterable[tuple[frozenset[str], str]]) -> str | None:
    tokens = set(re.split(r"[^a-z0-9]+", name.lower()))
    return next((key for vocabulary, key in words if tokens & vocabulary), None)


def _assign_defaults(model, words, asset_ids: dict[str, int]) -> list[str]:
    assigned = []
    with transaction.atomic():
        for row in model.objects.select_for_update().filter(visual_model__isnull=True).order_by("pk"):
            key = match_reference(row.name, words)
            if key is None:
                continue
            # Filtered again on the update so a choice saved meanwhile is kept.
            if model.objects.filter(pk=row.pk, visual_model__isnull=True).update(visual_model_id=asset_ids[key]):
                assigned.append(f"{row.name} → {key}")
    return assigned


def seed_reference_models(*, storage: ModelStorage | None = None, assign_defaults: bool = True) -> SeedReport:
    storage = storage or DjangoModelStorage()
    report = SeedReport()
    asset_ids: dict[str, int] = {}
    for model in REFERENCE_MODELS:
        details = AssetDetails(name=model.name, license=LICENSE, surface=model.surface)
        asset, created = store_asset(build_glb(model), details, storage=storage)
        asset_ids[model.key] = asset.pk
        (report.created if created else report.existing).append(model.name)
    if assign_defaults:
        report.station_types = _assign_defaults(StationType, STATION_TYPE_WORDS, asset_ids)
        report.equipment_categories = _assign_defaults(EquipmentCategory, CATEGORY_WORDS, asset_ids)
    return report
