import json
import struct
from dataclasses import replace

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APIClient

from core.labs.features.visual_models.application import save_model
from core.labs.features.visual_models.contracts import SaveModelInput
from core.labs.features.visual_models.exceptions import InvalidModel, ModelConflict
from core.labs.features.visual_models.validation import validate_glb
from core.labs.models.visual_models import VisualModel
from tests.factories import UserFactory, grant_labs_role


def glb(**extra):
    metadata = {"asset": {"version": "2.0"}, "meshes": [{"primitives": []}], **extra}
    chunk = json.dumps(metadata).encode()
    chunk += b" " * (-len(chunk) % 4)
    return struct.pack("<4sIIII", b"glTF", 2, 20 + len(chunk), len(chunk), 0x4E4F534A) + chunk


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


class MemoryStorage:
    def __init__(self):
        self.files = {}

    def save(self, content):
        name = str(len(self.files)) + ".glb"
        self.files[name] = content
        return name

    def delete(self, name):
        self.files.pop(name, None)


@pytest.mark.django_db
def test_stale_save_keeps_existing_file_and_cleans_new_upload():
    actor = grant_labs_role(UserFactory.create(), "coord")
    storage = MemoryStorage()
    data = SaveModelInput(scope="bench", target_key="*", name="Workbench", content=glb(), expected_version=0)
    model = save_model(data, actor=actor, storage=storage)
    old_file = model.file.name
    with pytest.raises(ModelConflict):
        save_model(replace(data, name="Stale edit"), actor=actor, storage=storage)
    model.refresh_from_db()
    assert model.name == "Workbench"
    assert model.version == 1
    assert set(storage.files) == {old_file}
    updated = save_model(replace(data, content=None, rotation=90, expected_version=1), actor=actor, storage=storage)
    assert updated.version == 2
    assert updated.file.name == old_file


@pytest.mark.django_db
def test_command_denies_non_operator():
    with pytest.raises(PermissionDenied):
        save_model(
            SaveModelInput(scope="bench", target_key="*", name="Bench", content=glb(), expected_version=0),
            actor=UserFactory.create(),
            storage=MemoryStorage(),
        )


@pytest.mark.django_db
def test_shared_upload_reload_placement_remove_and_permissions(tmp_path):
    client = APIClient()
    client.force_authenticate(user=grant_labs_role(UserFactory.create(), "coord"))
    with override_settings(MEDIA_ROOT=str(tmp_path), MINIO_ENABLED=False):
        response = client.put(
            "/api/labs/visual-models/equipment_category/4",
            {
                "file": SimpleUploadedFile("scope.glb", glb()),
                "name": "Oscilloscope",
                "scale": 0.8,
                "rotation": 90,
                "surface": 0.75,
                "offset_y": 0.2,
                "license": "Fixture",
                "source_url": "https://example.com/model",
            },
            format="multipart",
            HTTP_IF_NONE_MATCH="*",
        )
        assert response.status_code == 200, response.data
        assert response.data["data"]["version"] == 1
        other = APIClient()
        other.force_authenticate(user=grant_labs_role(UserFactory.create(), "coord"))
        loaded = other.get("/api/labs/visual-models?page_size=100")
        assert loaded.status_code == 200, loaded.data
        assert loaded.data["data"][0]["offset_y"] == 0.2
        assert loaded.data["data"][0]["url"]
        stale = client.delete("/api/labs/visual-models/equipment_category/4", HTTP_IF_MATCH='"2"')
        assert stale.status_code == 412
        removed = client.delete("/api/labs/visual-models/equipment_category/4", HTTP_IF_MATCH='"1"')
        assert removed.status_code == 204
        assert not VisualModel.objects.exists()
        other.force_authenticate(user=UserFactory.create())
        assert other.get("/api/labs/visual-models").status_code == 403


@pytest.mark.django_db
def test_upload_limit_and_query_validation():
    client = APIClient()
    client.force_authenticate(user=grant_labs_role(UserFactory.create(), "coord"))
    assert client.get("/api/labs/visual-models?page_size=no").status_code == 400
    assert client.delete("/api/labs/visual-models/bench/1?expected_version=no").status_code == 400
    response = client.put(
        "/api/labs/visual-models/bench/1",
        {
            "file": SimpleUploadedFile("large.glb", b"X" * (16 * 1024 * 1024)),
            "name": "Oversize",
        },
        format="multipart",
        HTTP_IF_NONE_MATCH="*",
    )
    assert response.status_code == 413
    assert not VisualModel.objects.exists()


@pytest.mark.django_db
def test_missing_precondition_and_update_headers(tmp_path):
    client = APIClient()
    client.force_authenticate(user=grant_labs_role(UserFactory.create(), "coord"))
    url = "/api/labs/visual-models/bench/*"
    assert client.put(url, {}, format="multipart").status_code == 428
    with override_settings(MEDIA_ROOT=str(tmp_path), MINIO_ENABLED=False):
        created = client.put(
            url,
            {
                "file": SimpleUploadedFile("bench.glb", glb()),
                "name": "Bench",
            },
            format="multipart",
            HTTP_IF_NONE_MATCH="*",
        )
        assert created.status_code == 200, created.data
        assert created["ETag"] == '"1"'
        updated = client.put(url, {"name": "Updated bench", "surface": "0.8"}, format="multipart", HTTP_IF_MATCH='"1"')
        assert updated.status_code == 200, updated.data
        assert updated["ETag"] == '"2"'
        stale = client.put(url, {"name": "Stale edit"}, format="multipart", HTTP_IF_MATCH='"1"')
        assert stale.status_code == 412
        assert client.delete(url).status_code == 428
        assert client.delete(url, HTTP_IF_MATCH='"2"').status_code == 204


@pytest.mark.django_db
def test_catalog_serialization_query_budget(django_assert_num_queries):
    from core.labs.features.visual_models.api.serializers import ModelSerializer
    from core.labs.features.visual_models.queries import list_models

    for key in ["1", "2", "3"]:
        VisualModel.objects.create(scope="equipment_category", target_key=key, name="Model", file="models/test.glb")
    with override_settings(MINIO_ENABLED=False), django_assert_num_queries(1):
        assert len(ModelSerializer(list_models(), many=True).data) == 3
