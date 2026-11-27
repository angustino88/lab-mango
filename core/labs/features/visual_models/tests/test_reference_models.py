import io
import json
import struct

import pytest
from django.core.management import call_command

from core.labs.features.visual_models.application.reference import match_reference, seed_reference_models
from core.labs.features.visual_models.reference_models import REFERENCE_MODELS, build_glb
from core.labs.features.visual_models.validation import validate_glb
from core.labs.models.resource.equipment.reference_data import EquipmentCategory
from core.labs.models.resource.location.station import StationType
from core.labs.models.visual_models import VisualModelAsset
from tests.factories import EquipmentCategoryFactory

from .test_library import MemoryStorage


def _bounds(content: bytes):
    length = struct.unpack_from("<I", content, 12)[0]
    data = json.loads(content[20 : 20 + length])
    positions = [a for a in data["accessors"] if "min" in a]
    low = [min(a["min"][k] for a in positions) for k in range(3)]
    high = [max(a["max"][k] for a in positions) for k in range(3)]
    return data, low, high


@pytest.mark.parametrize("model", REFERENCE_MODELS, ids=lambda model: model.key)
def test_reference_models_are_valid_deterministic_and_stand_on_the_floor(model):
    content = build_glb(model)
    validate_glb(content)
    assert content == build_glb(model)
    data, low, high = _bounds(content)
    assert abs(low[1]) < 1e-6  # stands on y = 0
    assert abs(low[0] + high[0]) < 0.05 and abs(low[2] + high[2]) < 0.1  # centred
    assert len(data["meshes"][0]["primitives"]) == len(data["materials"])
    assert len(content) < 512 * 1024


@pytest.mark.parametrize(
    ("key", "expected_surface_m"),
    [
        ("lab-workbench", 0.904),
        ("esd-corner-bench", 0.904),
        ("mobile-lab-cart", 0.878),
        ("fume-hood", 0.922),
        ("hil-test-rack", 0.983),
        ("embedded-test-rack", 0.908),
        ("cable-tray-overhead", 0.900),
    ],
)
def test_work_surface_models_align_with_their_deck_height(key, expected_surface_m):
    model = next(item for item in REFERENCE_MODELS if item.key == key)
    _data, low, high = _bounds(build_glb(model))
    assert model.surface * (high[1] - low[1]) == pytest.approx(expected_surface_m, abs=0.015)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Server rack", "server-rack"),
        ("Embedded test rack", "embedded-test-rack"),
        ("Workbench", "lab-workbench"),
        ("ESD work table", "lab-workbench"),
        ("ESD corner bench", "esd-corner-bench"),
        ("Chemical cabinet", "storage-cabinet"),
        ("Flammable safety cabinet", "safety-cabinet"),
        ("SMD component drawer cabinet", "component-drawer-cabinet"),
        ("Wall shelving", "storage-shelving"),
        ("Fume hood", "fume-hood"),
        ("HIL simulator rack", "hil-test-rack"),
        ("Thermal test chamber", "thermal-chamber"),
        ("Mobile instrument cart", "mobile-lab-cart"),
        ("Overhead power gantry", "cable-tray-overhead"),
        ("ESD lab stool", "lab-chair"),
        ("Cleanroom airlock", None),
    ],
)
def test_station_type_names_match_reference_models(name, expected):
    from core.labs.features.visual_models.application.reference import STATION_TYPE_WORDS

    assert match_reference(name, STATION_TYPE_WORDS) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Vector VN1630A", "vector-vn1630a"),
        ("Vector CANcaseXL", "vector-vn1630a"),
        ("Vector VN5620", "vector-vn5620"),
        ("Vector VT8012A HIL Chassis", "vector-vt-system"),
        ("Lauterbach TRACE32 PowerDebug", "lauterbach-powerdebug"),
        ("SEGGER J-Link PRO", "segger-jlink"),
        ("Saleae Logic Pro 16", "logic-analyzer-debugger"),
        ("Raspberry Pi 5", "raspberry-pi"),
        ("STMicroelectronics NUCLEO-H743ZI2", "stm32-nucleo-board"),
        ("Bosch ADAS ECU Gen4", "automotive-ecu-dut"),
        ("Rigol DP831", "rigol-dp831"),
        ("Toellner TOE 8952", "toellner-toe8952"),
        ("ITECH IT8512A+ Electronic Load", "electronic-dc-load"),
        ("Keysight 33522B Waveform Generator", "waveform-generator"),
        ("Fluke 87V Multimeter", "fluke-multimeter"),
        ("Keysight 34461A Benchtop DMM", "benchtop-instrument"),
        ("AmScope Trinocular Stereo Microscope", "stereo-microscope"),
        ("Weller WT2M Soldering Station", "soldering-rework-station"),
        ("Tektronix MSO54", "oscilloscope"),
        ("Dell OptiPlex 7010", "computer"),
        ("Dell UltraSharp Monitor", "monitor"),
        ("Generic Bracket X1", None),
    ],
)
def test_product_model_names_match_reference_models(name, expected):
    from core.labs.features.visual_models.application.reference import PRODUCT_MODEL_WORDS

    assert match_reference(name, PRODUCT_MODEL_WORDS) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Computing", "computer"),
        ("Display", "monitor"),
        ("Debugging", "logic-analyzer-debugger"),
        ("Networking", "network-switch"),
        ("Power", "dc-power-supply"),
        ("Furniture", "lab-chair"),
        ("Instrument", "benchtop-instrument"),
        ("Oscilloscope", "oscilloscope"),
        ("RF spectrum analyzer", "rf-signal-analyzer"),
        ("Soldering rework", "soldering-rework-station"),
        ("Rack UPS", "rack-ups-pdu"),
        ("ECU dev board", "embedded-dev-kit"),
        ("Sample", None),
    ],
)
def test_equipment_category_names_match_reference_models(name, expected):
    from core.labs.features.visual_models.application.reference import CATEGORY_WORDS

    assert match_reference(name, CATEGORY_WORDS) == expected


@pytest.mark.django_db
def test_seed_adds_models_once_and_only_fills_empty_defaults():
    rack = StationType.objects.create(name="Server rack")
    airlock = StationType.objects.create(name="Cleanroom airlock")
    storage = MemoryStorage()
    chosen = seed_reference_models(storage=storage, assign_defaults=False)
    assert len(chosen.created) == len(REFERENCE_MODELS) and not chosen.station_types
    rack.refresh_from_db()
    assert rack.visual_model_id is None

    custom = VisualModelAsset.objects.get(name="Reference · Monitor")
    bench = StationType.objects.create(name="Workbench", visual_model=custom)  # someone's choice

    report = seed_reference_models(storage=storage)
    assert not report.created and len(report.existing) == len(REFERENCE_MODELS)
    assert storage.saved == len(REFERENCE_MODELS)
    assert report.station_types == ["Server rack → server-rack"]
    for row in (rack, bench, airlock):
        row.refresh_from_db()
    assert rack.visual_model is not None
    assert rack.visual_model.name == "Reference · Server rack 42U"
    assert bench.visual_model_id == custom.pk
    assert airlock.visual_model_id is None
    assert seed_reference_models(storage=storage).station_types == []


@pytest.mark.django_db
def test_command_sets_equipment_category_defaults(monkeypatch):
    from core.labs.features.visual_models.application import reference

    monkeypatch.setattr(reference, "DjangoModelStorage", MemoryStorage)
    expected = {
        "Computing": "computer",
        "Display": "monitor",
        "Debugging": "logic-analyzer-debugger",
        "Networking": "network-switch",
        "Power": "dc-power-supply",
        "Furniture": "lab-chair",
        "Sample": None,
    }
    for name in expected:
        EquipmentCategoryFactory.create(name=name, definition=name)
    out = io.StringIO()
    call_command("seed_reference_models", stdout=out)
    assert f"Added {len(REFERENCE_MODELS)} model(s)" in out.getvalue()
    names = {model.name: model.key for model in REFERENCE_MODELS}
    for name, key in expected.items():
        category = EquipmentCategory.objects.get(name=name)
        assert (names[category.visual_model.name] if category.visual_model else None) == key, name
