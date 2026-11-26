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


def test_workbench_surface_is_the_worktop_height():
    workbench = next(model for model in REFERENCE_MODELS if model.key == "lab-workbench")
    _data, low, high = _bounds(build_glb(workbench))
    assert workbench.surface * (high[1] - low[1]) == pytest.approx(0.904, abs=0.01)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Server rack", "server-rack"),
        ("Workbench", "lab-workbench"),
        ("ESD work table", "lab-workbench"),
        ("Chemical cabinet", "storage-cabinet"),
        ("Wall shelving", "storage-shelving"),
        ("Fume hood", None),
    ],
)
def test_station_type_names_match_reference_models(name, expected):
    from core.labs.features.visual_models.application.reference import STATION_TYPE_WORDS

    assert match_reference(name, STATION_TYPE_WORDS) == expected


@pytest.mark.django_db
def test_seed_adds_models_once_and_only_fills_empty_defaults():
    rack = StationType.objects.create(name="Server rack")
    fume_hood = StationType.objects.create(name="Fume hood")
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
    rack.refresh_from_db(), bench.refresh_from_db(), fume_hood.refresh_from_db()
    assert rack.visual_model.name == "Reference · Server rack 42U"
    assert bench.visual_model_id == custom.pk
    assert fume_hood.visual_model_id is None
    assert seed_reference_models(storage=storage).station_types == []


@pytest.mark.django_db
def test_command_sets_equipment_category_defaults(monkeypatch):
    from core.labs.features.visual_models.application import reference

    monkeypatch.setattr(reference, "DjangoModelStorage", MemoryStorage)
    expected = {"Computing": "computer", "Display": "monitor", "Debugging": "benchtop-instrument", "Sample": None}
    for name in expected:
        EquipmentCategoryFactory.create(name=name, definition=name)
    out = io.StringIO()
    call_command("seed_reference_models", stdout=out)
    assert f"Added {len(REFERENCE_MODELS)} model(s)" in out.getvalue()
    names = {model.name: model.key for model in REFERENCE_MODELS}
    for name, key in expected.items():
        category = EquipmentCategory.objects.get(name=name)
        assert (names[category.visual_model.name] if category.visual_model else None) == key, name
