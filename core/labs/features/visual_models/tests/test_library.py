import json
import struct
from dataclasses import replace

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import ProtectedError
from django.test import override_settings
from rest_framework.test import APIClient

from core.labs.features.visual_models.application import (
    assign_model,
    delete_asset,
    update_asset,
    upload_asset,
)
from core.labs.features.visual_models.contracts import AssetDetails, AssignmentFit
from core.labs.features.visual_models.exceptions import AssetInUse, InvalidModel, ModelConflict
from core.labs.features.visual_models.validation import validate_glb
from core.labs.models.visual_models import VisualModelAsset, VisualModelAssignment
from tests.factories import UserFactory, grant_labs_role


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
        glb(extensionsRequired=["KHR_draco_mesh_compression"]),
    ],
)
def test_rejects_invalid_or_external_models(content):
    with pytest.raises(InvalidModel):
        validate_glb(content)


@pytest.mark.django_db
def test_identical_upload_reuses_the_library_asset(operator):
    storage = MemoryStorage()
    first, created = upload_asset(glb(), AssetDetails(name="Scope"), actor=operator, storage=storage)
    again, created_again = upload_asset(glb(), AssetDetails(name="Copy"), actor=operator, storage=storage)
    assert created and not created_again
    assert again.pk == first.pk and again.name == "Scope"
    assert storage.saved == 1 and VisualModelAsset.objects.count() == 1


@pytest.mark.django_db
def test_many_targets_share_one_asset_and_it_cannot_be_deleted_while_assigned(operator):
    storage = MemoryStorage()
    asset, _ = upload_asset(glb(), AssetDetails(name="Scope"), actor=operator, storage=storage)
    for scope, key in [("equipment_category", "4"), ("equipment", "12"), ("equipment_model", "7")]:
        assign_model(scope, key, AssignmentFit(asset_id=asset.pk), expected_version=0, actor=operator)
    assert VisualModelAssignment.objects.filter(asset=asset).count() == 3
    with pytest.raises(AssetInUse) as exc:
        delete_asset(asset.pk, expected_version=1, actor=operator, storage=storage)
    assert exc.value.usage_count == 3
    with pytest.raises(ProtectedError):
        asset.delete()
    VisualModelAssignment.objects.all().delete()
    delete_asset(asset.pk, expected_version=1, actor=operator, storage=storage)
    assert not VisualModelAsset.objects.exists()


@pytest.mark.django_db
def test_versions_guard_asset_and_assignment_edits(operator):
    asset, _ = upload_asset(glb(), AssetDetails(name="Bench"), actor=operator, storage=MemoryStorage())
    updated = update_asset(asset.pk, AssetDetails(name="Bench", surface=0.8), expected_version=1, actor=operator)
    assert updated.version == 2
    unchanged = update_asset(asset.pk, AssetDetails(name="Bench", surface=0.8), expected_version=2, actor=operator)
    assert unchanged.version == 2
    with pytest.raises(ModelConflict):
        update_asset(asset.pk, AssetDetails(name="Stale"), expected_version=1, actor=operator)

    fit = AssignmentFit(asset_id=asset.pk, scale=0.8)
    created = assign_model("bench", "*", fit, expected_version=0, actor=operator)
    assert created.version == 1
    with pytest.raises(ModelConflict):
        assign_model("bench", "*", fit, expected_version=0, actor=operator)
    moved = assign_model("bench", "*", replace(fit, offset_y=0.2), expected_version=1, actor=operator)
    assert moved.version == 2
    with pytest.raises(InvalidModel):
        assign_model("bench", "*", replace(fit, asset_id=999999), expected_version=2, actor=operator)


@pytest.mark.django_db
def test_commands_deny_non_operator():
    with pytest.raises(PermissionDenied):
        upload_asset(glb(), AssetDetails(name="Bench"), actor=UserFactory.create(), storage=MemoryStorage())


@pytest.mark.django_db
def test_upload_assign_reload_and_remove_over_http(client, tmp_path):
    with override_settings(MEDIA_ROOT=str(tmp_path), MINIO_ENABLED=False):
        response = client.post(
            "/api/labs/visual-model-assets",
            {
                "file": SimpleUploadedFile("scope.glb", glb()),
                "name": "Oscilloscope",
                "rotation": 90,
                "license": "Fixture",
                "source_url": "https://example.com/model",
            },
            format="multipart",
        )
        assert response.status_code == 201, response.data
        asset = response.data["data"]
        assert asset["usage_count"] == 0 and asset["version"] == 1 and asset["url"]
        duplicate = client.post(
            "/api/labs/visual-model-assets",
            {"file": SimpleUploadedFile("again.glb", glb()), "name": "Again"},
            format="multipart",
        )
        assert duplicate.status_code == 200, duplicate.data
        assert duplicate.data["data"]["id"] == asset["id"]

        for key in ["4", "5"]:
            assigned = client.put(
                f"/api/labs/visual-model-assignments/equipment_category/{key}",
                {"asset_id": asset["id"], "scale": 0.8, "offset_y": 0.2},
                format="json",
                HTTP_IF_NONE_MATCH="*",
            )
            assert assigned.status_code == 200, assigned.data
            assert assigned["ETag"] == '"1"'

        other = APIClient()
        other.force_authenticate(user=grant_labs_role(UserFactory.create(), "coord"))
        assets = other.get("/api/labs/visual-model-assets?page_size=100")
        assert assets.status_code == 200, assets.data
        assert assets.data["data"][0]["usage_count"] == 2
        assignments = other.get("/api/labs/visual-model-assignments?page_size=100")
        assert [row["target_key"] for row in assignments.data["data"]] == ["4", "5"]
        assert assignments.data["data"][0]["offset_y"] == 0.2

        in_use = client.delete(f"/api/labs/visual-model-assets/{asset['id']}", HTTP_IF_MATCH='"1"')
        assert in_use.status_code == 409
        for key in ["4", "5"]:
            url = f"/api/labs/visual-model-assignments/equipment_category/{key}"
            assert client.delete(url, HTTP_IF_MATCH='"2"').status_code == 412
            assert client.delete(url, HTTP_IF_MATCH='"1"').status_code == 204
            assert client.delete(url, HTTP_IF_MATCH='"1"').status_code == 404
        assert client.delete(f"/api/labs/visual-model-assets/{asset['id']}", HTTP_IF_MATCH='"1"').status_code == 204

        other.force_authenticate(user=UserFactory.create())
        assert other.get("/api/labs/visual-model-assets").status_code == 403
        assert other.get("/api/labs/visual-model-assignments").status_code == 403


@pytest.mark.django_db
def test_asset_metadata_update_requires_current_version(client):
    asset, _ = upload_asset(
        glb(),
        AssetDetails(name="Bench"),
        actor=grant_labs_role(UserFactory.create(), "coord"),
        storage=MemoryStorage(),
    )
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
    assert client.delete("/api/labs/visual-model-assignments/bench/1?expected_version=no").status_code == 400
    response = client.post(
        "/api/labs/visual-model-assets",
        {"file": SimpleUploadedFile("large.glb", b"X" * (16 * 1024 * 1024)), "name": "Oversize"},
        format="multipart",
    )
    assert response.status_code == 413
    assert not VisualModelAsset.objects.exists()


@pytest.mark.django_db
def test_assignment_rejects_unknown_scope_and_missing_precondition(client, operator):
    asset, _ = upload_asset(glb(), AssetDetails(name="Rack"), actor=operator, storage=MemoryStorage())
    body = {"asset_id": asset.pk}
    assert client.put("/api/labs/visual-model-assignments/bench/1", body, format="json").status_code == 428
    bad = client.put("/api/labs/visual-model-assignments/room/1", body, format="json", HTTP_IF_NONE_MATCH="*")
    assert bad.status_code == 422


@pytest.mark.django_db
def test_catalog_serialization_query_budget(django_assert_num_queries):
    from core.labs.features.visual_models.api.serializers import AssetSerializer, AssignmentSerializer
    from core.labs.features.visual_models.queries import list_assets, list_assignments

    for index in range(3):
        asset = VisualModelAsset.objects.create(name="Model", file="models/test.glb", sha256=f"{index:064x}", size=1)
        VisualModelAssignment.objects.create(scope="equipment_category", target_key=str(index + 1), asset=asset)
    with override_settings(MINIO_ENABLED=False), django_assert_num_queries(2):
        assert len(AssetSerializer(list_assets(), many=True).data) == 3
        assert len(AssignmentSerializer(list_assignments(), many=True).data) == 3
