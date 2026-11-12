"""Geographic catalog and selector views (ADR 002)."""

from typing import Any

from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.common.api.options import OptionsQueryMixin, SizeClass
from core.common.api.pagination import PageNumberQuerySerializer, with_page_query
from core.labs.features.base import FeatureAPIView
from core.labs.features.base.common import OptionsAPIView
from core.labs.features.locations.queries import (
    get_building,
    get_city,
    get_country,
    list_building_options,
    list_buildings,
    list_cities,
    list_city_options,
    list_countries,
    list_country_options,
)

from .geo_serializers import (
    BuildingOptionsQuerySerializer,
    BuildingSerializer,
    CityOptionsQuerySerializer,
    CitySerializer,
    CountrySerializer,
)


class CountryListAPIView(AppListAPIView, FeatureAPIView):
    schema_tags = ("Locations",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("CountryCatalogList", CountrySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self.list_response_sync(list_countries())


class CountryDetailAPIView(FeatureAPIView):
    schema_tags = ("Locations",)
    get_contract = OperationContract(
        success=ResponseContract.success("CountryCatalogDetail", CountrySerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, country_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_country(country_id=country_id))


class CountryOptionsAPIView(OptionsAPIView):
    query_serializer = OptionsQueryMixin
    size_class = SizeClass.SMALL
    owner = "locations"
    schema_tags = ("Locations",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_country_options(actor=actor, **filters)


class CityListAPIView(AppListAPIView, FeatureAPIView):
    schema_tags = ("Locations",)
    get_contract = OperationContract(
        query=with_page_query(CityOptionsQuerySerializer),
        success=ResponseContract.paginated("CityCatalogList", CitySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        country_id = query.get("country_id") if query else None
        return self.list_response_sync(list_cities(search=query.get("q") if query else None, country_id=country_id))


class CityDetailAPIView(FeatureAPIView):
    schema_tags = ("Locations",)
    get_contract = OperationContract(
        success=ResponseContract.success("CityCatalogDetail", CitySerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, city_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_city(city_id=city_id))


class CityOptionsAPIView(OptionsAPIView):
    query_serializer = CityOptionsQuerySerializer
    size_class = SizeClass.LARGE
    owner = "locations"
    schema_tags = ("Locations",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_city_options(actor=actor, **filters)


class BuildingListAPIView(AppListAPIView, FeatureAPIView):
    schema_tags = ("Locations",)
    get_contract = OperationContract(
        query=with_page_query(BuildingOptionsQuerySerializer),
        success=ResponseContract.paginated("BuildingCatalogList", BuildingSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        city_id = query.get("city_id") if query else None
        return self.list_response_sync(list_buildings(search=query.get("q") if query else None, city_id=city_id))


class BuildingDetailAPIView(FeatureAPIView):
    schema_tags = ("Locations",)
    get_contract = OperationContract(
        success=ResponseContract.success("BuildingCatalogDetail", BuildingSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, building_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_building(building_id=building_id))


class BuildingOptionsAPIView(OptionsAPIView):
    query_serializer = BuildingOptionsQuerySerializer
    size_class = SizeClass.LARGE
    owner = "locations"
    schema_tags = ("Locations",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_building_options(actor=actor, **filters)
