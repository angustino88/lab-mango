"""Resource images: ``image_url`` on every resource read and ``/{resource}/{id}/image`` upload endpoints."""

import io
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from core.labs.models import License, ResourceChangeLog, Room, Station, StationType
from core.labs.models.resource.license.license import LicenseCategory, LicenseProduct, LicenseType, LicenseVendor
from core.users.models import User
from tests.factories import BenchFactory, create_computing_equipment, grant_labs_role

RESOURCES = ("benches", "equipment", "licenses", "rooms", "stations")


def _png(name="photo.png", fmt="PNG", size=(8, 8)) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(0, 128, 255)).save(buffer, format=fmt)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def _make(kind: str):
    if kind == "benches":
        return BenchFactory()
    if kind == "equipment":
        return create_computing_equipment(sku="IMG-EQ-1", name="Scope")
    if kind == "licenses":
        return License.objects.create(
            name="CAD",
            sku="IMG-LIC-1",
            identifier="IMG-LIC-1",
            category=LicenseCategory.objects.create(name="Img category"),
            product=LicenseProduct.objects.create(name="Img product"),
            vendor=LicenseVendor.objects.create(name="Img vendor"),
            type=LicenseType.objects.create(name="Img type"),
        )
    if kind == "rooms":
        return Room.objects.create(name="Img room", sku="IMG-ROOM-1")
    return Station.objects.create(name="Img station", sku="IMG-ST-1", type=StationType.objects.create(name="Img"))


DETAIL_PATHS = {
    "benches": "/api/labs/benches/{id}",
    "equipment": "/api/labs/equipment/{id}",
    "licenses": "/api/labs/licenses/{id}",
    "rooms": "/api/labs/rooms/{id}",
    "stations": "/api/labs/stations/{id}",
}


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.MINIO_ENABLED = False
    return tmp_path


@pytest.fixture
def coordinator(db):
    return grant_labs_role(User.objects.create_user(username="img-coord"), "coord")


@pytest.fixture
def client(coordinator):
    api = APIClient()
    api.force_authenticate(coordinator)
    return api


def _url(kind, resource):
    return f"/api/labs/{kind}/{resource.pk}/image"


@pytest.mark.django_db
@pytest.mark.parametrize("kind", RESOURCES)
def test_upload_returns_url_and_resource_read_exposes_it(client, kind):
    resource = _make(kind)

    uploaded = client.put(_url(kind, resource), {"file": _png()}, format="multipart")

    assert uploaded.status_code == 200, uploaded.data
    image_url = uploaded.data["data"]["image_url"]
    assert image_url.startswith("http://testserver/media/") and image_url.endswith(".png")
    assert client.get(_url(kind, resource)).data["data"] == {"image_url": image_url}
    detail = client.get(DETAIL_PATHS[kind].format(id=resource.pk))
    assert detail.status_code == 200, detail.data
    assert detail.data["data"]["image_url"] == image_url


@pytest.mark.django_db
@pytest.mark.parametrize("kind", RESOURCES)
def test_resource_without_image_reads_null(client, kind):
    resource = _make(kind)

    assert client.get(_url(kind, resource)).data["data"] == {"image_url": None}
    assert client.get(DETAIL_PATHS[kind].format(id=resource.pk)).data["data"]["image_url"] is None


@pytest.mark.django_db
def test_equipment_list_rows_carry_image_url(client):
    equipment = _make("equipment")
    client.put(_url("equipment", equipment), {"file": _png()}, format="multipart")

    rows = client.get("/api/labs/equipment").data["data"]

    assert rows[0]["image_url"].endswith(".png")


@pytest.mark.django_db
def test_storage_name_is_server_generated_not_client_filename(client):
    bench = _make("benches")

    client.put(_url("benches", bench), {"file": _png(name="../../etc/evil.png")}, format="multipart")

    bench.refresh_from_db()
    assert ".." not in bench.image.name
    assert "evil" not in bench.image.name


@pytest.mark.django_db(transaction=True)
def test_replace_deletes_previous_file_after_commit(client):
    bench = _make("benches")
    client.put(_url("benches", bench), {"file": _png()}, format="multipart")
    bench.refresh_from_db()
    first = bench.image.name
    storage = bench.image.storage

    client.put(_url("benches", bench), {"file": _png()}, format="multipart")

    bench.refresh_from_db()
    assert bench.image.name != first
    assert storage.exists(bench.image.name)
    assert not storage.exists(first)


@pytest.mark.django_db(transaction=True)
def test_delete_clears_image_and_is_idempotent(client):
    station = _make("stations")
    client.put(_url("stations", station), {"file": _png()}, format="multipart")
    station.refresh_from_db()
    name, storage = station.image.name, station.image.storage

    first = client.delete(_url("stations", station))
    second = client.delete(_url("stations", station))

    assert (first.status_code, second.status_code) == (204, 204)
    station.refresh_from_db()
    assert not station.image
    assert not storage.exists(name)
    assert ResourceChangeLog.objects.for_resource(station).filter(field_name="image").count() == 2  # set, cleared


@pytest.mark.django_db
def test_upload_records_change_log_with_actor(client, coordinator):
    room = _make("rooms")

    client.put(_url("rooms", room), {"file": _png()}, format="multipart")

    room.refresh_from_db()
    log = ResourceChangeLog.objects.for_resource(room).get(field_name="image")
    assert log.action == ResourceChangeLog.Action.UPDATE
    assert (log.old_value, log.new_value) == (None, room.image.name)
    assert log.last_modified_by_id == coordinator.pk


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_missing_or_soft_deleted_resource_is_404(client, method):
    room = _make("rooms")
    room.soft_delete()

    def kwargs():
        return {"data": {"file": _png()}, "format": "multipart"} if method == "put" else {}

    deleted = getattr(client, method)(_url("rooms", room), **kwargs())
    missing = getattr(client, method)("/api/labs/rooms/999999/image", **kwargs())

    assert (deleted.status_code, missing.status_code) == (404, 404)


@pytest.mark.django_db
def test_non_image_content_is_422_even_with_image_content_type(client):
    bench = _make("benches")
    fake = SimpleUploadedFile("photo.png", b"not an image", content_type="image/png")

    response = client.put(_url("benches", bench), {"file": fake}, format="multipart")

    assert response.status_code == 422
    assert response.data["error"]["details"][0]["field"] == "file"


@pytest.mark.django_db
def test_detected_type_outside_allowlist_is_415(client):
    bench = _make("benches")
    # Real BMP bytes declared as PNG: the sniffed type decides.
    bmp = _png(name="photo.png", fmt="BMP")

    response = client.put(_url("benches", bench), {"file": bmp}, format="multipart")

    assert response.status_code == 415
    assert response.data["error"]["code"] == "unsupported_media_type"
    bench.refresh_from_db()
    assert not bench.image


@pytest.mark.django_db
def test_oversized_image_is_413(client):
    bench = _make("benches")

    with patch("core.labs.features.base.resource_images.MAX_RESOURCE_IMAGE_BYTES", 10):
        response = client.put(_url("benches", bench), {"file": _png()}, format="multipart")

    assert response.status_code == 413
    assert response.data["error"]["code"] == "payload_too_large"


@pytest.mark.django_db
def test_json_body_is_415(client):
    bench = _make("benches")

    response = client.put(_url("benches", bench), {"file": "aGVsbG8="}, format="json")

    assert response.status_code == 415


@pytest.mark.django_db
def test_missing_unknown_and_duplicate_file_parts_are_422(client):
    bench = _make("benches")
    url = _url("benches", bench)

    missing = client.put(url, {}, format="multipart")
    unknown = client.put(url, {"file": _png(), "caption": "x"}, format="multipart")
    duplicate = client.put(url, {"file": [_png(), _png(name="b.png")]}, format="multipart")

    assert [r.status_code for r in (missing, unknown, duplicate)] == [422, 422, 422]
    assert unknown.data["error"]["details"][0]["code"] == "unknown_field"
    assert duplicate.data["error"]["details"][0]["code"] == "duplicate_values"


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_plain_labs_user_is_forbidden(method):
    user = grant_labs_role(User.objects.create_user(username="img-member"), "user")
    api = APIClient()
    api.force_authenticate(user)
    bench = _make("benches")
    kwargs = {"data": {"file": _png()}, "format": "multipart"} if method == "put" else {}

    response = getattr(api, method)(_url("benches", bench), **kwargs)

    assert response.status_code == 403


@pytest.mark.django_db
def test_anonymous_is_rejected():
    bench = _make("benches")

    response = APIClient().get(_url("benches", bench))

    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_minio_mode_returns_presigned_url_everywhere(client, settings):
    equipment = _make("equipment")
    client.put(_url("equipment", equipment), {"file": _png()}, format="multipart")
    settings.MINIO_ENABLED = True
    signed = "https://minio.example/media/resources/x.png?X-Amz-Signature=ok"

    with patch("core.infrastructure.storage.urls.generate_presigned_url", return_value=signed):
        image = client.get(_url("equipment", equipment)).data["data"]["image_url"]
        detail = client.get(f"/api/labs/equipment/{equipment.pk}").data["data"]["image_url"]

    assert image == detail == signed


@pytest.mark.django_db
def test_stored_file_is_removed_when_resource_vanishes_before_lock(media_root):
    from core.labs.features.base.resource_image_commands import (
        ReplaceResourceImageInput,
        ResourceImageTargetNotFound,
        replace_resource_image,
    )
    from core.labs.models import Bench

    bench = _make("benches")

    with (
        patch("core.labs.features.base.resource_image_commands._lock", side_effect=ResourceImageTargetNotFound),
        pytest.raises(ResourceImageTargetNotFound),
    ):
        replace_resource_image(model=Bench, data=ReplaceResourceImageInput(resource_id=bench.pk, image=_png()))

    assert [path for path in media_root.rglob("*") if path.is_file()] == []
