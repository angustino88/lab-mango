"""Unit tests for shared options base primitives in core.common.api.options."""

from unittest.mock import MagicMock

import pytest
from rest_framework import serializers, status
from rest_framework.test import force_authenticate

from core.common.api.options import (
    CatalogOptionSerializer,
    IncludeIDsField,
    OptionsAPIView,
    OptionsQueryMixin,
    SizeClass,
)


class DummyOptionsQuerySerializer(OptionsQueryMixin):
    category_id = serializers.IntegerField(required=False, min_value=1)


class SmallDummyOptionsAPIView(OptionsAPIView):
    query_serializer = DummyOptionsQuerySerializer
    size_class = SizeClass.SMALL
    owner = "test"
    data = None

    def select(self, *, actor, filters):
        if self.data is not None:
            return self.data
        return [
            {"id": 1, "sku": "CODE1", "name": "Alpha"},
            {"id": 2, "sku": None, "name": "Beta"},
        ]


class LargeDummyOptionsAPIView(OptionsAPIView):
    query_serializer = DummyOptionsQuerySerializer
    size_class = SizeClass.LARGE
    required_any = ("q", "category_id")
    owner = "test"

    def select(self, *, actor, filters):
        return [{"id": 10, "sku": "L1", "name": "Large Item"}]


@pytest.fixture()
def auth_user():
    user = MagicMock()
    user.is_authenticated = True
    user.pk = 1
    return user


def test_catalog_option_serializer_serializes_id_sku_name():
    data = {"id": 1, "sku": "SKU-1", "name": "Test Item"}
    serializer = CatalogOptionSerializer(instance=data)
    assert serializer.data == data


def test_catalog_option_serializer_allows_null_sku():
    data = {"id": 2, "sku": None, "name": "Test Null SKU"}
    serializer = CatalogOptionSerializer(instance=data)
    assert serializer.data == data


def test_include_ids_field_validation():
    field = IncludeIDsField()
    assert field.run_validation("1,2,3") == [1, 2, 3]

    with pytest.raises(serializers.ValidationError) as exc:
        field.run_validation("1,2,2")
    assert exc.value.detail[0].code == "duplicate_values"

    with pytest.raises(serializers.ValidationError) as exc:
        field.run_validation("1,0,3")
    assert "invalid_format" in str(exc.value)

    with pytest.raises(serializers.ValidationError) as exc:
        field.run_validation(",".join(str(i) for i in range(1, 52)))
    assert exc.value.detail[0].code == "max_items"


def test_options_query_mixin_rejects_empty_q():
    serializer = DummyOptionsQuerySerializer(data={"q": ""})
    assert not serializer.is_valid()
    assert "q" in serializer.errors


@pytest.mark.asyncio
async def test_small_options_view_returns_all_without_filters(rf, auth_user):
    view = SmallDummyOptionsAPIView.as_view()
    request = rf.get("/test/options")
    force_authenticate(request, user=auth_user)
    response = await view(request)

    assert response.status_code == status.HTTP_200_OK
    assert response.data == {
        "data": [
            {"id": 1, "sku": "CODE1", "name": "Alpha"},
            {"id": 2, "sku": None, "name": "Beta"},
        ]
    }
    assert "ETag" in response.headers
    assert response.headers["Cache-Control"] == "private, no-cache"
    assert "Accept-Language" in response.headers["Vary"]


@pytest.mark.asyncio
async def test_etag_matches_returns_304(rf, auth_user):
    view = SmallDummyOptionsAPIView.as_view()
    request1 = rf.get("/test/options")
    force_authenticate(request1, user=auth_user)
    response1 = await view(request1)
    etag = response1.headers["ETag"]

    request2 = rf.get("/test/options", HTTP_IF_NONE_MATCH=etag)
    force_authenticate(request2, user=auth_user)
    response2 = await view(request2)

    assert response2.status_code == status.HTTP_304_NOT_MODIFIED
    assert response2.headers["ETag"] == etag
    assert response2.headers["Cache-Control"] == "private, no-cache"


@pytest.mark.asyncio
async def test_large_options_view_requires_q_or_parent_filter(rf, auth_user):
    view = LargeDummyOptionsAPIView.as_view()
    request = rf.get("/test/options")
    force_authenticate(request, user=auth_user)
    response = await view(request)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "invalid_query"
    assert response.headers["Cache-Control"] == "no-store"

    # With q provided
    request_q = rf.get("/test/options", {"q": "item"})
    force_authenticate(request_q, user=auth_user)
    response_q = await view(request_q)
    assert response_q.status_code == status.HTTP_200_OK

    # With category_id provided
    request_cat = rf.get("/test/options", {"category_id": 5})
    force_authenticate(request_cat, user=auth_user)
    response_cat = await view(request_cat)
    assert response_cat.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_unknown_query_parameter_rejected(rf, auth_user):
    view = SmallDummyOptionsAPIView.as_view()
    request = rf.get("/test/options", {"sort": "name"})
    force_authenticate(request, user=auth_user)
    response = await view(request)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "invalid_query"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_repeated_query_parameter_rejected(rf, auth_user):
    view = SmallDummyOptionsAPIView.as_view()
    request = rf.get("/test/options?category_id=1&category_id=2")
    force_authenticate(request, user=auth_user)
    response = await view(request)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "invalid_query"


@pytest.mark.asyncio
async def test_too_many_results_returns_400(rf, auth_user):
    data = [{"id": i, "sku": None, "name": f"Item {i}"} for i in range(15)]

    class CappedOptionsAPIView(SmallDummyOptionsAPIView):
        max_results = 10

    view = CappedOptionsAPIView.as_view(data=data)
    request = rf.get("/test/options")
    force_authenticate(request, user=auth_user)
    response = await view(request)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "too_many_results"
    assert response.headers["Cache-Control"] == "no-store"
