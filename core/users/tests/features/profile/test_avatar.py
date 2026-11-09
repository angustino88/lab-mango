import io
from unittest.mock import patch

import pytest
from PIL import Image

from core.users.tests.conftest import make_access_token


def make_image_file(fmt="PNG", size=(100, 100), suffix="test.png") -> io.BytesIO:
    img = Image.new("RGB", size, color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    buf.seek(0)
    buf.name = suffix
    return buf


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_upload_avatar_success(api_client, user):
    token = await make_access_token(user)

    image = make_image_file()
    resp = await api_client.post(
        "/api/users/avatar",
        data={"avatar": image},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "avatar_url" in body
    assert "avatar" not in body


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_avatar_urls_use_shared_helper_in_minio_mode(api_client, user, settings):
    token = await make_access_token(user)
    settings.MINIO_ENABLED = True

    signed_url = "https://minio.example/avatars/test.png?signature=ok"
    image = make_image_file()

    # NOTE: default_storage stays local in test env; only the URL resolution
    # path (get_media_url → generate_presigned_url) is exercised here.
    with patch("core.infrastructure.storage.urls.generate_presigned_url", return_value=signed_url):
        upload_resp = await api_client.post(
            "/api/users/avatar",
            data={"avatar": image},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert upload_resp.status_code == 200
        assert upload_resp.json()["data"]["avatar_url"] == signed_url
        assert "avatar" not in upload_resp.json()["data"]

        list_resp = await api_client.get(
            "/api/users?username=testuser",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert list_resp.status_code == 200
        assert list_resp.json()["data"][0]["avatar_url"] == signed_url


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_avatar(api_client, user):
    token = await make_access_token(user)

    resp = await api_client.get(
        "/api/users/avatar",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "avatar_url" in body
    assert "avatar" not in body


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_delete_avatar_when_none_returns_404(api_client, user):
    token = await make_access_token(user)

    resp = await api_client.delete(
        "/api/users/avatar",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_upload_oversized_avatar_returns_422(api_client, user):
    """Files > 5MB must be rejected."""
    token = await make_access_token(user)

    large_buf = io.BytesIO(b"x" * (6 * 1024 * 1024))
    large_buf.name = "big.png"

    resp = await api_client.post(
        "/api/users/avatar",
        data={"avatar": large_buf},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_upload_without_avatar_returns_validation_problem(api_client, user):
    token = await make_access_token(user)
    response = await api_client.post(
        "/api/users/avatar",
        data={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "avatar"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_delete_avatar_returns_bodyless_204(api_client, user):
    token = await make_access_token(user)
    image = make_image_file()
    upload = await api_client.post(
        "/api/users/avatar",
        data={"avatar": image},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upload.status_code == 200
    response = await api_client.delete(
        "/api/users/avatar",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204
    assert not response.content


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_avatar_unauthenticated_returns_401(api_client):
    resp = await api_client.get("/api/users/avatar")
    assert resp.status_code == 401
