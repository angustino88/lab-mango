import json
import struct

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APIClient

from core.labs.features.visual_models.application import (
    delete_asset,
    select_visual_model,
    update_asset,
    upload_asset,
)
from core.labs.features.visual_models.contracts import AssetDetails
from core.labs.features.visual_models.exceptions import AssetInUse, InvalidModel, ModelConflict
from core.labs.features.visual_models.queries import effective_visual_models
from core.labs.features.visual_models.validation import validate_glb
from core.labs.models import Equipment, Station
from core.labs.models.resource.equipment.reference_data import (
    EquipmentManufacturer,
    EquipmentProductModel,
    EquipmentType,
)
from core.labs.models.resource.location.station import StationType
from core.labs.models.visual_models import VisualModelAsset
from tests.factories import (
    BenchFactory,
    ComputingEquipmentFactory,
    UserFactory,
    grant_labs_role,
)


def glb(**extra):
    metadata = {"asset": {"version": "2.0"}, "meshes": [{"primitives": []}], **extra}
    chunk = json.dumps(metadata).encode()
    chunk += b" " * (-len(chunk) % 4)
    return struct.pack("<4sIIII", b"glTF", 2, 20 + len(chunk), len(chunk), 0x4E4F534A) + chunk


class MemoryStorage:
    def __init__(self):
        self.files = {}
        self.saved = 0

    def save(self, content):
        self.saved += 1
        name = f"{self.saved}.glb"
        self.files[name] = content
        return name

    def delete(self, name):
        self.files.pop(name, None)


@pytest.fixture
def operator():
    return grant_labs_role(UserFactory.create(), "coord")


@pytest.fixture
def client(operator):
    api = APIClient()
    api.force_authenticate(user=operator)
    return api


@pytest.mark.parametrize(
    "content",
    [
        b"not a glb",
        glb(buffers=[{"uri": "https://example.com/data.bin"}]),
        glb(images=[{"uri": "../texture.png"}]),
        glb(extensionsRequired=["EXT_unknown_decoder"]),
    ],
)
def test_rejects_invalid_or_external_models(content):
    with pytest.raises(InvalidModel):
        validate_glb(content)


@pytest.mark.parametrize(
    "extension",
    ["KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_mesh_quantization", "KHR_texture_basisu"],
)
def test_accepts_compressed_models_the_dashboard_can_decode(extension):
    validate_glb(glb(extensionsUsed=[extension], extensionsRequired=[extension]))


@pytest.mark.django_db
def test_identical_upload_reuses_the_library_asset(operator):
    storage = MemoryStorage()
    first, created = upload_asset(glb(), AssetDetails(name="Scope"), actor=operator, storage=storage)
    again, created_again = upload_asset(glb(), AssetDetails(name="Copy"), actor=operator, storage=storage)
    assert created and not created_again
    assert again.pk == first.pk and again.name == "Scope"
    assert storage.saved == 1 and VisualModelAsset.objects.count() == 1


def _asset(operator, name="Model", **extra):
    asset, _ = upload_asset(glb(**extra), AssetDetails(name=name), actor=operator, storage=MemoryStorage())
    return asset


@pytest.mark.django_db
def test_equipment_shows_its_own_then_product_model_then_category_model(operator):
    device = ComputingEquipmentFactory.create()
    category_model = _asset(operator, "Category", extras={"n": 1})
    product_model = _asset(operator, "Product", extras={"n": 2})
    own_model = _asset(operator, "Own", extras={"n": 3})
    category_id = device.kind.category_id

    assert effective_visual_models("equipment", [device.pk]) == {device.pk: None}
    select_visual_model("equipment-categories", category_id, category_model.pk, actor=operator)
    selection = select_visual_model("equipment", device.pk, None, actor=operator)
    assert (selection.effective_visual_model_id, selection.origin) == (category_model.pk, "equipment_category")
    manufacturer = EquipmentManufacturer.objects.create(name="Acme")
    manufacturer.categories.add(device.kind.category)
    equipment_type = EquipmentType.objects.create(kind=device.kind, name="Scope")
    catalog_model = EquipmentProductModel.objects.create(
        manufacturer=manufacturer, equipment_type=equipment_type, name="X100"
    )
    Equipment.objects.filter(pk=device.pk).update(product_model=catalog_model)
    select_visual_model("equipment-product-models", catalog_model.pk, product_model.pk, actor=operator)
    selection = select_visual_model("equipment", device.pk, None, actor=operator)
    assert (selection.effective_visual_model_id, selection.origin) == (product_model.pk, "product_model")
    selection = select_visual_model("equipment", device.pk, own_model.pk, actor=operator)
    assert (selection.visual_model_id, selection.origin) == (own_model.pk, "own")
    assert Equipment.objects.get(pk=device.pk).visual_model_id == own_model.pk


@pytest.mark.django_db
def test_station_inherits_station_type_model_and_bench_stores_its_own(operator):
    workbench = _asset(operator, "Workbench")
    station_type = StationType.objects.create(name="Workbench")
    bench = BenchFactory.create()
    station = Station.objects.create(sku="ST-VM-1", name="Station", type=station_type)
    select_visual_model("station-types", station_type.pk, workbench.pk, actor=operator)
    assert effective_visual_models("stations", [station.pk]) == {station.pk: workbench.pk}
    select_visual_model("benches", bench.pk, workbench.pk, actor=operator)
    assert effective_visual_models("benches", [bench.pk]) == {bench.pk: workbench.pk}
    with pytest.raises(InvalidModel):
        select_visual_model("benches", bench.pk, 999999, actor=operator)


@pytest.mark.django_db
def test_used_asset_cannot_be_deleted_and_counts_every_table(operator):
    storage = MemoryStorage()
    asset, _ = upload_asset(glb(), AssetDetails(name="Scope"), actor=operator, storage=storage)
    device = ComputingEquipmentFactory.create()
    bench = BenchFactory.create()
    select_visual_model("equipment", device.pk, asset.pk, actor=operator)
    select_visual_model("benches", bench.pk, asset.pk, actor=operator)
    select_visual_model("equipment-categories", device.kind.category_id, asset.pk, actor=operator)
    with pytest.raises(AssetInUse) as exc:
        delete_asset(asset.pk, expected_version=1, actor=operator, storage=storage)
    assert exc.value.usage_count == 3
    for segment, pk in (
        ("equipment", device.pk),
        ("benches", bench.pk),
        ("equipment-categories", device.kind.category_id),
    ):
        select_visual_model(segment, pk, None, actor=operator)
    delete_asset(asset.pk, expected_version=1, actor=operator, storage=storage)
    assert not VisualModelAsset.objects.exists()


@pytest.mark.django_db
def test_asset_versions_guard_metadata_edits(operator):
    asset = _asset(operator, "Bench")
    updated = update_asset(asset.pk, AssetDetails(name="Bench", surface=0.8), expected_version=1, actor=operator)
    assert updated.version == 2
    unchanged = update_asset(asset.pk, AssetDetails(name="Bench", surface=0.8), expected_version=2, actor=operator)
    assert unchanged.version == 2
    with pytest.raises(ModelConflict):
        update_asset(asset.pk, AssetDetails(name="Stale"), expected_version=1, actor=operator)


@pytest.mark.django_db
def test_commands_deny_non_operator(operator):
    with pytest.raises(PermissionDenied):
        upload_asset(glb(), AssetDetails(name="Bench"), actor=UserFactory.create(), storage=MemoryStorage())
    bench = BenchFactory.create()
    with pytest.raises(PermissionDenied):
        select_visual_model("benches", bench.pk, None, actor=UserFactory.create())


@pytest.mark.django_db
def test_upload_select_and_read_over_http(client, tmp_path):
    device = ComputingEquipmentFactory.create()
    category_id = device.kind.category_id
    with override_settings(MEDIA_ROOT=str(tmp_path), MINIO_ENABLED=False):
        response = client.post(
            "/api/labs/visual-model-assets",
            {"file": SimpleUploadedFile("scope.glb", glb()), "name": "Oscilloscope", "license": "Fixture"},
            format="multipart",
        )
        assert response.status_code == 201, response.data
        asset = response.data["data"]
        duplicate = client.post(
            "/api/labs/visual-model-assets",
            {"file": SimpleUploadedFile("again.glb", glb()), "name": "Again"},
            format="multipart",
        )
        assert duplicate.status_code == 200 and duplicate.data["data"]["id"] == asset["id"]

        url = f"/api/labs/equipment-categories/{category_id}/visual-model"
        selected = client.put(url, {"visual_model_id": asset["id"]}, format="json")
        assert selected.status_code == 200, selected.data
        assert selected.data["data"]["visual_model_id"] == asset["id"]

        inherited = client.get(f"/api/labs/equipment/{device.pk}/visual-model")
        assert inherited.status_code == 200, inherited.data
        assert inherited.data["data"]["visual_model_id"] is None
        assert inherited.data["data"]["effective_visual_model_id"] == asset["id"]
        assert inherited.data["data"]["origin"] == "equipment_category"

        defaults = client.get("/api/labs/visual-model-selections/equipment-categories?page_size=100")
        assert defaults.status_code == 200, defaults.data
        row = next(item for item in defaults.data["data"] if item["id"] == category_id)
        assert row["visual_model_id"] == asset["id"] and row["name"]

        assets = client.get("/api/labs/visual-model-assets?page_size=100")
        assert assets.data["data"][0]["usage_count"] == 1
        assert client.delete(f"/api/labs/visual-model-assets/{asset['id']}", HTTP_IF_MATCH='"1"').status_code == 409
        assert client.put(url, {"visual_model_id": None}, format="json").status_code == 200
        assert client.delete(f"/api/labs/visual-model-assets/{asset['id']}", HTTP_IF_MATCH='"1"').status_code == 204

    assert client.put(url, {"visual_model_id": 999999}, format="json").status_code == 422
    assert client.get("/api/labs/equipment/999999/visual-model").status_code == 404
    assert client.get("/api/labs/visual-model-selections/rooms").status_code == 404
    other = APIClient()
    other.force_authenticate(user=UserFactory.create())
    assert other.get("/api/labs/visual-model-assets").status_code == 403
    assert other.put(url, {"visual_model_id": None}, format="json").status_code == 403


@pytest.mark.django_db
def test_asset_metadata_update_requires_current_version(client, operator):
    asset = _asset(operator, "Bench")
    url = f"/api/labs/visual-model-assets/{asset.pk}"
    body = {"name": "Workbench", "surface": 0.75, "license": "CC-BY-4.0"}
    assert client.put(url, body, format="json").status_code == 428
    with override_settings(MINIO_ENABLED=False):
        updated = client.put(url, body, format="json", HTTP_IF_MATCH='"1"')
    assert updated.status_code == 200, updated.data
    assert updated["ETag"] == '"2"' and updated.data["data"]["surface"] == 0.75
    assert client.put(url, body, format="json", HTTP_IF_MATCH='"1"').status_code == 412
    assert (
        client.put("/api/labs/visual-model-assets/999999", body, format="json", HTTP_IF_MATCH='"1"').status_code == 404
    )


@pytest.mark.django_db
def test_upload_limit_and_query_validation(client):
    assert client.get("/api/labs/visual-model-assets?page_size=no").status_code == 400
    response = client.post(
        "/api/labs/visual-model-assets",
        {"file": SimpleUploadedFile("large.glb", b"X" * (16 * 1024 * 1024)), "name": "Oversize"},
        format="multipart",
    )
    assert response.status_code == 413
    assert not VisualModelAsset.objects.exists()


@pytest.mark.django_db
def test_catalog_queries_have_fixed_cost(django_assert_num_queries, operator):
    from core.labs.features.visual_models.api.serializers import AssetSerializer
    from core.labs.features.visual_models.queries import list_assets, list_selections

    for index in range(3):
        asset = VisualModelAsset.objects.create(name="Model", file="models/test.glb", sha256=f"{index:064x}", size=1)
        StationType.objects.create(name=f"Type {index}", visual_model=asset)
    with override_settings(MINIO_ENABLED=False), django_assert_num_queries(2):
        assert len(AssetSerializer(list_assets(), many=True).data) == 3
        assert len(list_selections("station-types")[0:10]) == 3


@pytest.mark.django_db
def test_room_mapping_rows_carry_the_shown_model(operator):
    from core.labs.features.resource_mappings.queries import get_resource_mapping

    workbench = _asset(operator, "Workbench")
    instrument = _asset(operator, "Instrument", extras={"n": 9})
    station_type = StationType.objects.create(name="Workbench")
    station = Station.objects.create(sku="ST-VM-2", name="Station", type=station_type)
    bench = BenchFactory.create(setup_location=station)
    select_visual_model("station-types", station_type.pk, workbench.pk, actor=operator)
    select_visual_model("benches", bench.pk, instrument.pk, actor=operator)

    mapping = get_resource_mapping(resource_type="stations", resource_id=station.pk)
    assert mapping is not None
    assert [(row["id"], row["visual_model_id"]) for row in mapping["data"]["stations"]] == [(station.pk, workbench.pk)]
    assert [(row["id"], row["visual_model_id"]) for row in mapping["data"]["benches"]] == [(bench.pk, instrument.pk)]
