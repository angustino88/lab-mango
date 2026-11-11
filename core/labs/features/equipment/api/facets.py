"""Thin inventory facet adapters sharing each equipment collection's filters."""

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from django.conf import settings
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.plumbing import ResolvedComponent
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.common.api.filtering import FilterSpec
from core.common.api.pagination import ResultsSetPagination
from core.labs.features.base.access import LABS_STAFF_ACCESS
from core.labs.features.equipment.api.common import EquipmentAPIView
from core.labs.features.equipment.api.resource_filters import EQUIPMENT_FILTERS
from core.labs.features.equipment.queries.equipment import list_equipment
from core.labs.features.equipment.queries.facets import EQUIPMENT_DIMENSIONS, equipment_facet_rows

if TYPE_CHECKING:
    from drf_spectacular.openapi import AutoSchema as ConfiguredAutoSchema
else:
    ConfiguredAutoSchema = type(EquipmentAPIView.schema)


class FacetValueSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class EquipmentFacetSerializer(serializers.Serializer):
    value = serializers.SerializerMethodField(method_name="get_facet_value")
    equipment_count = serializers.IntegerField(read_only=True, min_value=1)

    @extend_schema_field(FacetValueSerializer(allow_null=True))
    def get_facet_value(self, row: Mapping[str, Any]) -> dict[str, Any] | None:
        if row["facet_id"] is None:
            return None
        return {"id": row["facet_id"], "name": row["facet_name"]}


def facet_filter_spec(list_spec: FilterSpec) -> FilterSpec:
    """Reuse membership/search definitions while deliberately forbidding ordering."""
    return FilterSpec(
        list_spec.filters,
        search_fields=list_spec.search_fields,
        ranges=list_spec.ranges,
        search_alias=list_spec.search_alias,
        search_distinct=list_spec.search_distinct,
    )


def facet_query_serializer(name: str, spec: FilterSpec) -> type[serializers.Serializer]:
    return type(
        name,
        (spec.serializer(f"{name}Filters"),),
        {
            "__module__": __name__,
            "dimension": serializers.ChoiceField(choices=tuple(EQUIPMENT_DIMENSIONS), required=True),
            "page": serializers.IntegerField(required=False, min_value=1, default=1),
            "page_size": serializers.IntegerField(required=False, min_value=1, max_value=100, default=25),
        },
    )


class EquipmentFacetsAutoSchema(ConfiguredAutoSchema):
    """Extend the configured project schema, not the runtime permission policy."""

    def get_auth(self) -> list[dict]:
        alternatives = super().get_auth()
        custom_header = getattr(settings, "API_KEY_CUSTOM_HEADER", None)
        header = custom_header.removeprefix("HTTP_").replace("_", "-") if custom_header else "Authorization"
        self.registry.register_on_missing(
            ResolvedComponent(
                name="equipmentFacetsApiKey",
                type=ResolvedComponent.SECURITY_SCHEMA,
                object=EquipmentFacetsAutoSchema,
                schema={
                    "type": "apiKey",
                    "in": "header",
                    "name": header,
                    "description": "Valid API key." if custom_header else "Use Authorization: Api-Key <key>.",
                },
            )
        )
        return [*alternatives, {"equipmentFacetsApiKey": []}]


class EquipmentFacetsAPIView(AppListAPIView, EquipmentAPIView):
    """Conjunctive distinct inventory counts, ordered by value name/id, null last."""

    permission_classes = LABS_STAFF_ACCESS
    schema = EquipmentFacetsAutoSchema()
    pagination_class = ResultsSetPagination
    queryset_provider: Callable = staticmethod(list_equipment)
    filter_spec = facet_filter_spec(EQUIPMENT_FILTERS)
    get_contract = OperationContract(
        query=facet_query_serializer("EquipmentFacetsQuerySerializer", filter_spec),
        success=ResponseContract.paginated("EquipmentFacets", EquipmentFacetSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        values, error = self.validate_query()
        if error is not None:
            # The shared base labels typed query failures validation_failed;
            # this new operation consistently uses the approved query code.
            error.data["error"]["code"] = "invalid_query"
            return error
        if values is None:
            raise TypeError("Successful query validation must return values")
        dimension = values["dimension"]
        filters = {key: value for key, value in values.items() if key not in {"dimension", "page", "page_size"}}
        population = self.filter_spec.apply(self.queryset_provider(), filters)
        rows = equipment_facet_rows(population=population, dimension=dimension)
        return self.list_response_sync(rows)
