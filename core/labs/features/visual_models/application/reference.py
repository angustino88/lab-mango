"""Seed the library with the built-in reference models and use them as catalog defaults.

Idempotent: identical bytes reuse the existing asset, and a default is only set on catalog rows that have no
model yet, so choices made by people are never overwritten.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from django.db import transaction

from core.labs.models.resource.equipment.reference_data import EquipmentCategory, EquipmentProductModel
from core.labs.models.resource.location.station import StationType

from ..contracts import AssetDetails, ModelStorage
from ..reference_models import REFERENCE_MODELS, build_glb
from . import store_asset
from .adapters import DjangoModelStorage

LICENSE = "Built-in LabMango reference model (original work, no third-party content)"

# Catalog name words → reference model key. Specific types come before general fallbacks.
STATION_TYPE_WORDS: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"testbench", "embedded", "dut"}), "embedded-test-rack"),
    (frozenset({"hil", "simulator"}), "hil-test-rack"),
    (frozenset({"chamber", "climatic", "thermal", "environmental", "oven"}), "thermal-chamber"),
    (frozenset({"fume", "hood", "extraction", "exhaust"}), "fume-hood"),
    (frozenset({"flammable", "hazard", "safety", "battery"}), "safety-cabinet"),
    (frozenset({"drawer", "drawers", "parts", "smd", "component"}), "component-drawer-cabinet"),
    (frozenset({"cart", "trolley", "mobile", "rolling"}), "mobile-lab-cart"),
    (frozenset({"gantry", "bridge", "overhead", "cableway"}), "cable-tray-overhead"),
    (frozenset({"corner"}), "esd-corner-bench"),
    (frozenset({"chair", "stool", "seating"}), "lab-chair"),
    (frozenset({"rack", "racks"}), "server-rack"),
    (frozenset({"table", "desk", "bench", "workbench", "workstation"}), "lab-workbench"),
    (frozenset({"cabinet", "enclosure", "locker"}), "storage-cabinet"),
    (frozenset({"shelf", "shelves", "shelving"}), "storage-shelving"),
)
CATEGORY_WORDS: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"oscilloscope", "scope", "mso", "dso"}), "oscilloscope"),
    (frozenset({"spectrum", "rf", "vna", "signal", "antenna"}), "rf-signal-analyzer"),
    (frozenset({"waveform", "generator", "awg", "function"}), "waveform-generator"),
    (frozenset({"load", "eload"}), "electronic-dc-load"),
    (frozenset({"multimeter", "dmm", "fluke"}), "fluke-multimeter"),
    (frozenset({"microscope", "optics", "inspection"}), "stereo-microscope"),
    (frozenset({"solder", "soldering", "rework", "hotair"}), "soldering-rework-station"),
    (frozenset({"ups", "pdu"}), "rack-ups-pdu"),
    (frozenset({"power", "psu", "supply", "battery"}), "dc-power-supply"),
    (frozenset({"networking", "network", "switch", "switches", "router", "ethernet", "lan"}), "network-switch"),
    (
        frozenset({"debugging", "debugger", "debug", "jtag", "swd", "logic", "probe", "trace"}),
        "logic-analyzer-debugger",
    ),
    (
        frozenset({"embedded", "board", "boards", "devkit", "dut", "ecu", "mcu", "fpga", "microcontroller", "target"}),
        "embedded-dev-kit",
    ),
    (frozenset({"furniture", "chair", "stool", "seating"}), "lab-chair"),
    (frozenset({"computing", "computer", "computers", "pc", "server", "servers", "workstation"}), "computer"),
    (frozenset({"display", "displays", "monitor", "monitors", "screen"}), "monitor"),
    (frozenset({"instrument", "instruments", "measurement", "test", "laboratory"}), "benchtop-instrument"),
)
# Specific hardware product model keywords (matched against "<manufacturer> <model name>").
PRODUCT_MODEL_WORDS: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"vt8012", "vt8012a", "vt8006", "vt1004", "vt2004", "vt6051", "vtsystem"}), "vector-vt-system"),
    (frozenset({"vn5620", "vn5610", "vn5610a", "vn5640", "vn5650"}), "vector-vn5620"),
    (
        frozenset({"vn1630", "vn1630a", "vn1640", "vn1640a", "vn1610", "vn1611", "cancase", "cancasexl"}),
        "vector-vn1630a",
    ),
    (frozenset({"lauterbach", "trace32", "powerdebug", "powertrace"}), "lauterbach-powerdebug"),
    (frozenset({"segger", "jlink", "jtrace"}), "segger-jlink"),
    (frozenset({"saleae", "logic16", "logicpro"}), "logic-analyzer-debugger"),
    (frozenset({"raspberry", "rpi", "rpi4", "rpi5", "raspi"}), "raspberry-pi"),
    (frozenset({"nucleo", "stm32", "stm32h7", "stm32f4", "stmicroelectronics"}), "stm32-nucleo-board"),
    (frozenset({"adas", "ecu", "domain", "powertrain", "bosch"}), "automotive-ecu-dut"),
    (frozenset({"dp831", "dp831a", "dp832", "dp832a", "dp821", "dp811", "rigol"}), "rigol-dp831"),
    (frozenset({"toellner", "toe8952", "toe8951", "8952", "8951", "8950"}), "toellner-toe8952"),
    (frozenset({"itech", "it8512", "it8512a", "it8511", "dl3021", "dl3031", "eload"}), "electronic-dc-load"),
    (frozenset({"33522b", "33500b", "33600a", "dg4000", "dg4162", "awg", "waveform"}), "waveform-generator"),
    (frozenset({"fluke", "87v", "179", "289", "handheld"}), "fluke-multimeter"),
    (frozenset({"34461a", "34465a", "8846a", "truevolt", "dmm"}), "benchtop-instrument"),
    (frozenset({"e36312a", "e36313a", "nge100", "nge103"}), "dc-power-supply"),
    (frozenset({"microscope", "amscope", "leica", "trinocular"}), "stereo-microscope"),
    (frozenset({"weller", "wt2m", "wt1010", "hakko", "fx888d", "quick861dw"}), "soldering-rework-station"),
    (frozenset({"oscilloscope", "mso", "dso", "tektronix", "rto", "rtb", "mxo"}), "oscilloscope"),
    (frozenset({"spectrum", "vna", "fsw", "fsv", "fsva"}), "rf-signal-analyzer"),
    (frozenset({"switch", "catalyst", "aruba", "netgear"}), "network-switch"),
    (frozenset({"ups", "smartups", "pdu", "apc"}), "rack-ups-pdu"),
    (frozenset({"monitor", "ultrasharp", "display", "thinkvision"}), "monitor"),
    (frozenset({"optiplex", "precision", "thinkstation", "thinkcentre", "desktop", "workstation"}), "computer"),
)


@dataclass
class SeedReport:
    created: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    station_types: list[str] = field(default_factory=list)
    equipment_categories: list[str] = field(default_factory=list)
    product_models: list[str] = field(default_factory=list)


def match_reference(name: str, words: Iterable[tuple[frozenset[str], str]]) -> str | None:
    tokens = set(re.split(r"[^a-z0-9]+", name.lower()))
    return next((key for vocabulary, key in words if tokens & vocabulary), None)


def _assign_defaults(model, words, asset_ids: dict[str, int], *, select_related: tuple[str, ...] = ()) -> list[str]:
    assigned = []
    with transaction.atomic():
        qs = model.objects.select_for_update().filter(visual_model__isnull=True).order_by("pk")
        if select_related:
            qs = qs.select_related(*select_related)
        for row in qs:
            label = f"{row.manufacturer.name} {row.name}" if select_related else row.name
            key = match_reference(label, words)
            if key is None:
                continue
            # Filtered again on the update so a choice saved meanwhile is kept.
            if model.objects.filter(pk=row.pk, visual_model__isnull=True).update(visual_model_id=asset_ids[key]):
                assigned.append(f"{label} → {key}")
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
        report.product_models = _assign_defaults(
            EquipmentProductModel, PRODUCT_MODEL_WORDS, asset_ids, select_related=("manufacturer",)
        )
    return report
