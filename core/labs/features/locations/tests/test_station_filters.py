"""Stations pilot: validation, SQL compilation, metadata and error responses."""

from unittest.mock import patch

import pytest
from django.http import QueryDict
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from core.common.api.filtering import FilterMetadataSerializer
from core.labs.features.locations.stations.api.filters import STATION_FILTERS
from core.labs.features.locations.stations.api.serializers import StationListQuerySerializer
from core.labs.features.locations.stations.api.views import StationFiltersAPIView, StationListCreateAPIView
from core.labs.features.locations.stations.queries.selectors import list_stations


def test_station_query_compiles_all_filters_without_database_access():
    serializer = StationListQuerySerializer(
        data=QueryDict(
            "room_id=1,2&type_id=3&status=available,retired&q=bench&ordering=-name"
            "&created_at_after=2026-01-01T00:00:00Z&created_at_before=2026-02-01T00:00:00Z"
        )
    )
    assert serializer.is_valid(), serializer.errors
    queryset = STATION_FILTERS.apply(list_stations(), serializer.validated_data)
    sql, params = queryset.query.sql_with_params()
    assert queryset.query.order_by == ("-name", "pk")
    assert "available" in params and "retired" in params
    assert 1 in params and 2 in params and 3 in params
    assert "IN" in sql and "SELECT" in sql


def test_station_openapi_matches_csv_wire_format_and_metadata_route():
    from drf_spectacular.generators import SchemaGenerator
    from drf_spectacular.validation import validate_schema

    from core.labs.features.locations.stations.api.urls import urlpatterns

    schema = SchemaGenerator(patterns=urlpatterns).get_schema(public=True)
    validate_schema(schema)
    parameters = {item["name"]: item for item in schema["paths"]["/stations"]["get"]["parameters"]}
    assert parameters["room_id"]["schema"]["type"] == "string"
    assert parameters["q"]["schema"]["maxLength"] == 200
    assert "ordering" in parameters and "status" in parameters
    assert "get" in schema["paths"]["/stations/filters"]


@pytest.mark.parametrize(
    "query,field",
    [
        ("room_id=1&room_id=2", "room_id"),
        ("status=nope", "status"),
        ("ordering=name,-name", "ordering"),
        ("unexpected=x", "unexpected"),
    ],
)
def test_station_view_returns_standard_400_before_query(query, field):
    view = StationListCreateAPIView()
    view.request = Request(APIRequestFactory().get("/api/stations?" + query))
    with patch.object(view, "_execute") as execute:
        response = view.handle_get(view.request)
    assert response.status_code == 400
    assert "error" in response.data
    assert any(detail["field"] == field for detail in response.data["error"]["details"])
    execute.assert_not_called()


def test_metadata_endpoint_uses_same_spec_and_envelope():
    view = StationFiltersAPIView()
    view.request = Request(APIRequestFactory().get("/api/stations/filters"))
    response = view.handle_get(view.request)
    assert response.status_code == 200
    assert response.data["data"] == STATION_FILTERS.metadata()
    serializer = FilterMetadataSerializer(data=response.data["data"])
    assert serializer.is_valid(), serializer.errors
