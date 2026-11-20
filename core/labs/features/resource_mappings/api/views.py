"""Authenticated HTTP adapters for graphic-only resource placement mappings."""

from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.urls import remove_query_param, replace_query_param

from core.common.api.api_views import AppAPIView
from core.labs.features.base.access import LAB_OPERATIONS_ACCESS

from ..queries import MappingPageNotFound, MappingQueryError, get_resource_mapping, list_bench_mappings
from .serializers import (
    BenchMappingListQuerySerializer,
    BenchMappingListResponseSerializer,
    ResourceMappingQuerySerializer,
    ResourceMappingResponseSerializer,
)


class ResourceMappingAPIView(AppAPIView):
    permission_classes = LAB_OPERATIONS_ACCESS
    schema_tags = ("Resource Mappings",)
    get_contract = OperationContract(
        query=ResourceMappingQuerySerializer,
        success=ResponseContract.documented(200, ResourceMappingResponseSerializer),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
    )

    resource_type = ""

    def handle_get(self, request: Request, resource_id: int, *args, **kwargs) -> Response:
        query, error = self._validated_mapping_query()
        if error is not None:
            return error
        try:
            result = get_resource_mapping(
                resource_type=self.resource_type,
                resource_id=resource_id,
                page_size=query["page_size"],
                cursors={
                    collection: query.get(f"{collection}_cursor")
                    for collection in (
                        "rooms", "room_slots", "stations", "station_slots", "benches", "equipment", "licenses",
                        "license_assignments",
                    )
                },
            )
        except MappingQueryError:
            return self.respond_problem("bad_request", code="invalid_query", detail="The mapping query is invalid.")
        if result is None:
            return self.respond_problem("not_found", code="not_found", detail="Resource not found.")
        return Response(ResourceMappingResponseSerializer(result).data)

    def _validated_mapping_query(self):
        serializer = ResourceMappingQuerySerializer(data=self.request.query_params)
        unknown = set(self.request.query_params) - set(serializer.fields)
        errors = {key: ["Unknown query parameter."] for key in sorted(unknown)}
        for key in set(serializer.fields) & set(self.request.query_params):
            if len(self.request.query_params.getlist(key)) != 1:
                errors[key] = ["This parameter must not be repeated."]
            elif key != "page_size" and not self.request.query_params.get(key):
                errors[key] = ["Cursor must not be blank."]
        if errors:
            return None, self.respond_problem("bad_request", code="invalid_query", errors=errors)
        if not serializer.is_valid():
            return None, self.respond_problem("bad_request", code="invalid_query", errors=serializer.errors)
        return serializer.validated_data, None


@extend_schema_view(
    get=extend_schema(
        parameters=[BenchMappingListQuerySerializer],
        summary="List bench mappings",
        description=(
            "One page of benches (ordered by SKU) with their station, room, slots, placed units and licenses, in the "
            "flat collection shape of the mapping reads. Filters and search run on the server; meta.summary counts "
            "the whole filtered set (before state)."
        ),
    )
)
class BenchMappingListAPIView(AppAPIView):
    permission_classes = LAB_OPERATIONS_ACCESS
    schema_tags = ("Resource Mappings",)
    get_contract = OperationContract(
        query=BenchMappingListQuerySerializer,
        success=ResponseContract.documented(200, BenchMappingListResponseSerializer),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        serializer = BenchMappingListQuerySerializer(data=request.query_params)
        unknown = set(request.query_params) - set(serializer.fields)
        errors = {key: ["Unknown query parameter."] for key in sorted(unknown)}
        for key in set(serializer.fields) & set(request.query_params):
            if len(request.query_params.getlist(key)) != 1:
                errors[key] = ["This parameter must not be repeated."]
        if errors:
            return self.respond_problem("bad_request", code="invalid_query", errors=errors)
        if not serializer.is_valid():
            return self.respond_problem("bad_request", code="invalid_query", errors=serializer.errors)
        query = dict(serializer.validated_data)
        page, page_size = query.pop("page"), query.pop("page_size")
        try:
            result = list_bench_mappings(page=page, page_size=page_size, **query)
        except MappingPageNotFound:
            return self.respond_problem("not_found", code="not_found", detail="Invalid page.")
        url = request.build_absolute_uri()
        has_next = page * page_size < result["count"]
        previous = None
        if page > 1:
            previous = remove_query_param(url, "page") if page == 2 else replace_query_param(url, "page", page - 1)
        meta = {
            "pagination": {
                "count": result["count"],
                "page": page,
                "page_size": page_size,
                "next": replace_query_param(url, "page", page + 1) if has_next else None,
                "previous": previous,
            },
            "summary": result["summary"],
        }
        return Response(BenchMappingListResponseSerializer({"data": result["data"], "meta": meta}).data)


@extend_schema_view(
    get=extend_schema(
        parameters=[ResourceMappingQuerySerializer],
        summary="Get room placement mapping",
        description="Returns flat graphic-only placement context for the selected room.",
    )
)
class RoomMappingAPIView(ResourceMappingAPIView):
    get_contract = ResourceMappingAPIView.get_contract
    resource_type = "rooms"


@extend_schema_view(
    get=extend_schema(
        parameters=[ResourceMappingQuerySerializer],
        summary="Get station placement mapping",
        description="Returns flat graphic-only placement context for the selected station.",
    )
)
class StationMappingAPIView(ResourceMappingAPIView):
    get_contract = ResourceMappingAPIView.get_contract
    resource_type = "stations"


@extend_schema_view(
    get=extend_schema(
        parameters=[ResourceMappingQuerySerializer],
        summary="Get bench placement mapping",
        description="Returns flat graphic-only placement context for the selected bench.",
    )
)
class BenchMappingAPIView(ResourceMappingAPIView):
    get_contract = ResourceMappingAPIView.get_contract
    resource_type = "benches"


@extend_schema_view(
    get=extend_schema(
        parameters=[ResourceMappingQuerySerializer],
        summary="Get equipment placement mapping",
        description="Returns flat graphic-only placement context for the selected equipment.",
    )
)
class EquipmentMappingAPIView(ResourceMappingAPIView):
    get_contract = ResourceMappingAPIView.get_contract
    resource_type = "equipment"
