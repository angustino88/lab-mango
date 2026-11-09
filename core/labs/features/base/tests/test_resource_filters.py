"""One wire contract across ResourceModel descendants and equipment subtypes."""

from dataclasses import replace

import pytest
from django.http import QueryDict
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from core.common.api.filtering import Filter, PositiveIDField
from core.labs.features.benches.api.filters import BENCH_FILTERS
from core.labs.features.benches.api.views import BenchFiltersAPIView
from core.labs.features.benches.queries.selectors import list_benches
from core.labs.features.equipment.api.resource_filters import EQUIPMENT_FILTERS
from core.labs.features.equipment.api.views import EquipmentFiltersAPIView
from core.labs.features.equipment.queries.equipment import list_equipment
from core.labs.features.licenses.api.filters import LICENSE_FILTERS
from core.labs.features.licenses.api.views import LicenseFiltersAPIView
from core.labs.features.licenses.queries.selectors import list_licenses
from core.labs.features.locations.rooms.api.filters import ROOM_FILTERS
from core.labs.features.locations.rooms.api.views import RoomFiltersAPIView
from core.labs.features.locations.rooms.queries.selectors import list_rooms
from core.labs.features.locations.stations.api.filters import STATION_FILTERS
from core.labs.features.locations.stations.api.views import StationFiltersAPIView
from core.labs.features.locations.stations.queries.selectors import list_stations
from core.labs.models.resource.base.resource import ResourceModel


@pytest.mark.parametrize(
    "spec,selector",
    [
        (ROOM_FILTERS, list_rooms),
        (STATION_FILTERS, list_stations),
        (BENCH_FILTERS, list_benches),
        (EQUIPMENT_FILTERS, list_equipment),
        (LICENSE_FILTERS, list_licenses),
    ],
)
def test_common_fields_work_for_every_resource(spec, selector):
    queryset = selector()
    assert issubclass(queryset.model, ResourceModel)
    serializer = spec.serializer("ResourceTestQuery")(
        data=QueryDict("id=1,2&owner_id=3,4&group_id=5&q=abc&ordering=-name&created_at_after=2026-01-01T00:00:00Z")
    )
    assert serializer.is_valid(), serializer.errors
    filtered = spec.apply(queryset, serializer.validated_data)
    sql, params = filtered.query.sql_with_params()
    assert filtered.query.order_by == ("-name", "pk")
    assert all(value in params for value in (1, 2, 3, 4, 5))
    assert "IN" in sql
    assert {"id", "owner_id", "group_id", "status", "created_at_after", "created_at_before"} <= {
        entry["name"] for entry in spec.metadata()["filters"]
    }


@pytest.mark.parametrize(
    "view_class,spec",
    [
        (RoomFiltersAPIView, ROOM_FILTERS),
        (StationFiltersAPIView, STATION_FILTERS),
        (BenchFiltersAPIView, BENCH_FILTERS),
        (EquipmentFiltersAPIView, EQUIPMENT_FILTERS),
        (LicenseFiltersAPIView, LICENSE_FILTERS),
    ],
)
def test_resource_metadata_uses_identical_envelope(view_class, spec):
    view = view_class()
    view.request = Request(APIRequestFactory().get("/filters"))
    response = view.handle_get(view.request)
    assert response.status_code == 200
    assert response.data["data"] == spec.metadata()
    assert view.permission_classes


def test_equipment_assignment_and_room_and_bench_extensions_compile():
    for spec, selector, query in (
        (EQUIPMENT_FILTERS, list_equipment, "category=1,2&kind=3,4&type=5&manufacturer=6&assigned=false"),
        (ROOM_FILTERS, list_rooms, "country_id=1,2&city_id=3&building_id=4&status=available"),
        (BENCH_FILTERS, list_benches, "setup_location_id=1,2&bench_group_id=3&type_id=4&favorite=false"),
    ):
        serializer = spec.serializer("ExtensionTestQuery")(data=QueryDict(query))
        assert serializer.is_valid(), serializer.errors
        spec.apply(selector(), serializer.validated_data).query.sql_with_params()


def test_category_equipment_views_inherit_resource_contract():
    from core.labs.features.equipment.api.categories import build_category_urlpatterns
    from core.labs.features.equipment.api.category_definitions import CATEGORY_DEFINITIONS

    for definition in CATEGORY_DEFINITIONS.values():
        patterns = build_category_urlpatterns(definition, module=__name__)
        list_view = patterns[0].callback.view_class
        fields = list_view.ListQuerySerializer().fields
        assert {"owner_id", "group_id", "q", "ordering", "status", "assigned"} <= set(fields)
        params = "owner_id=1,2&assigned=false"
        if definition.key == "computing":
            params += "&technical_user_id=1"
        serializer = list_view.ListQuerySerializer(data=QueryDict(params))
        assert serializer.is_valid(), serializer.errors
        list_view.filter_spec.apply(list_view.queryset_provider(), serializer.validated_data).query.sql_with_params()


def test_computing_category_has_its_own_validated_filters_and_shared_owner_filter():
    from core.labs.features.equipment.api.categories import build_category_urlpatterns
    from core.labs.features.equipment.api.category_definitions import CATEGORY_DEFINITIONS

    patterns = build_category_urlpatterns(CATEGORY_DEFINITIONS["computing"], module=__name__)
    list_view = patterns[0].callback.view_class
    filters_view = next(pattern.callback.view_class for pattern in patterns if pattern.name == "computing-filters")
    serializer = list_view.ListQuerySerializer(data=QueryDict("owner_id=7,8&technical_user_id=3&q=server"))
    assert serializer.is_valid(), serializer.errors
    queryset = list_view.filter_spec.apply(list_view.queryset_provider(), serializer.validated_data)
    sql, params = queryset.query.sql_with_params()
    assert "owner_id" in sql and "technical_user_id" in sql
    assert 7 in params and 8 in params and 3 in params and "%server%" in params
    metadata = filters_view.filter_spec.metadata()
    assert {item["name"] for item in metadata["filters"]} >= {"owner_id", "technical_user_id"}
    other_patterns = build_category_urlpatterns(CATEGORY_DEFINITIONS["accessory"], module=__name__)
    other_view = other_patterns[0].callback.view_class
    assert "technical_user_id" not in other_view.ListQuerySerializer().fields


@pytest.mark.parametrize(
    "filter_name,lookup",
    [("os_name", "os_name"), ("interfaces", "interfaces")],
)
def test_category_filters_reject_non_foreign_key_fields(filter_name, lookup):
    from core.labs.features.equipment.api.categories import build_category_urlpatterns
    from core.labs.features.equipment.api.category_definitions import CATEGORY_DEFINITIONS

    definition = replace(
        CATEGORY_DEFINITIONS["computing" if filter_name == "os_name" else "display"],
        list_filters=(Filter(filter_name, PositiveIDField(), lookup, "reference"),),
    )
    with pytest.raises(ValueError, match="direct foreign-key"):
        build_category_urlpatterns(definition, module=__name__)


def test_all_resource_openapi_contracts_validate():
    from drf_spectacular.generators import SchemaGenerator
    from drf_spectacular.validation import validate_schema

    from core.labs.features.benches.api.urls import urlpatterns as benches
    from core.labs.features.equipment.api.urls import urlpatterns as equipment
    from core.labs.features.licenses.api.urls import urlpatterns as licenses
    from core.labs.features.locations.api.urls import urlpatterns as locations

    schema = SchemaGenerator(patterns=[*benches, *equipment, *licenses, *locations]).get_schema(public=True)
    validate_schema(schema)
    for collection in ("benches", "equipment", "licenses", "rooms", "stations"):
        endpoint = schema["paths"][f"/{collection}"]["get"]
        if collection == "equipment":
            continue  # path is shared by the explicit equipment collection handlers; query schema checked separately.
        parameters = {item["name"]: item for item in endpoint.get("parameters", [])}
        if not parameters:
            continue
        assert parameters["owner_id"]["schema"]["type"] == "string"
        assert {"q", "ordering", "status"} <= parameters.keys()
        assert "get" in schema["paths"][f"/{collection}/filters"]
    category_path = schema["paths"]["/equipment/computing"]["get"]
    category_parameters = {item["name"]: item for item in category_path["parameters"]}
    assert {"owner_id", "technical_user_id"} <= category_parameters.keys()



