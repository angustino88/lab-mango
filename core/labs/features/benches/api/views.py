"""Authenticated bench HTTP boundary and method-specific response contracts."""

from django.utils import timezone  # noqa: F401
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.permissions import IsAuthenticated

from core.common.api.api_views import AppListAPIView
from core.common.api.filtering import FilterMetadataMixin, FilterMetadataSerializer
from core.common.api.options import OptionsAPIView, OptionsQueryMixin, SizeClass
from core.common.api.pagination import PageNumberQuerySerializer
from core.labs.features.base import CommandAPIView, operation
from core.labs.features.benches.application import services
from core.labs.features.benches.queries import selectors

# Import the functions, not the submodule: the package re-exports a selector
# function also named ``reference_data`` that shadows the submodule attribute.
from core.labs.features.benches.queries.reference_data import (
    list_bench_group_options,
    list_bench_type_options,
)
from core.labs.features.benches.queries.summaries import get_bench_status_summary

from .filters import BENCH_FILTERS
from .serializers import (
    BenchCreateSerializer,
    BenchEquipmentListQuerySerializer,
    BenchFavoriteSerializer,
    BenchGroupSerializer,
    BenchListQuerySerializer,
    BenchPlacementSerializer,
    BenchReferenceDataSerializer,
    BenchReferenceWriteSerializer,
    BenchResourceDetailSerializer,
    BenchSelectQuerySerializer,
    BenchSerializer,
    BenchSetupEquipmentSerializer,
    BenchStatusSummarySerializer,
    BenchTypeSerializer,
    BenchUpdateSerializer,
)


class BenchAPIView(AppListAPIView, CommandAPIView):
    permission_classes = [IsAuthenticated]
    schema_tags = ("Benches",)

    def project_result(self, result):
        return selectors.get_bench(bench_id=result.pk, actor=self.request.user)


class BenchStatusSummaryAPIView(BenchAPIView):
    """Non-deleted benches by lifecycle state, not activity or bookings."""

    get_contract = OperationContract(
        success=ResponseContract.success("BenchStatusSummaryData", BenchStatusSummarySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request, **kwargs):
        if request.query_params:
            return self.respond_problem("bad_request", code="invalid_query", detail="This endpoint accepts no query parameters.")
        return self._execute(get_bench_status_summary)


class BenchListCreateAPIView(BenchAPIView):
    get_contract = operation("BenchList", BenchSerializer, query=BenchListQuerySerializer, many=True)
    post_contract = operation("BenchCreate", BenchSerializer, request=BenchCreateSerializer, created=True)

    def handle_get(self, request, **kwargs):
        filters, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: BENCH_FILTERS.apply(selectors.list_benches(actor=request.user), filters))

    def handle_post(self, request, **kwargs):
        return self._write(services.create_bench, project=True)


class BenchFiltersAPIView(FilterMetadataMixin, BenchAPIView):
    filter_spec = BENCH_FILTERS
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.success("BenchFilters", FilterMetadataSerializer),
    )


class BenchDetailAPIView(BenchAPIView):
    get_contract = OperationContract(
        success=ResponseContract.success("BenchDetail", BenchResourceDetailSerializer),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
    )
    put_contract = operation("BenchReplace", BenchSerializer, request=BenchUpdateSerializer)
    patch_contract = operation("BenchUpdate", BenchSerializer, request=BenchUpdateSerializer)
    delete_contract = operation("BenchDelete", None, delete=True)

    def handle_get(self, request, bench_id, **kwargs):
        if request.query_params:
            errors = {key: ["Query parameters are not supported for bench detail."] for key in request.query_params}
            return self.respond_problem("bad_request", code="invalid_query", errors=errors)
        return self._execute(lambda: selectors.get_bench(bench_id=bench_id, actor=request.user))

    def handle_put(self, request, bench_id, **kwargs):
        return self._write(services.update_bench, lookup={"bench_id": bench_id}, project=True)

    def handle_patch(self, request, bench_id, **kwargs):
        return self._write(services.update_bench, lookup={"bench_id": bench_id}, partial=True, project=True)

    def handle_delete(self, request, bench_id, **kwargs):
        return self._execute(lambda: services.delete_bench(bench_id=bench_id, actor=request.user), delete=True)


class BenchPlaceAPIView(BenchAPIView):
    patch_contract = operation("BenchPlacement", BenchSerializer, request=BenchPlacementSerializer)
    post_contract = operation("BenchPlaceAction", BenchSerializer, request=BenchPlacementSerializer)

    def handle_patch(self, request, bench_id, **kwargs):
        return self._write(services.place_bench, lookup={"bench_id": bench_id}, project=True)

    def handle_post(self, request, bench_id, **kwargs):
        return self._write(services.place_bench, lookup={"bench_id": bench_id}, project=True)


class BenchFavoriteAPIView(BenchAPIView):
    post_contract = operation("BenchFavorite", BenchFavoriteSerializer)
    delete_contract = operation("BenchFavoriteDelete", None, delete=True)

    def handle_post(self, request, bench_id, **kwargs):
        return self._execute(lambda: services.add_favorite(bench_id=bench_id, actor=request.user))

    def handle_delete(self, request, bench_id, **kwargs):
        return self._execute(lambda: services.remove_favorite(bench_id=bench_id, actor=request.user), delete=True)


@extend_schema_view(
    post=extend_schema(
        deprecated=True,
        description="Deprecated alias. Use DELETE /api/labs/benches/{bench_id}/actions/favorite instead.",
    ),
)
class BenchUnfavoriteActionAPIView(BenchAPIView):
    post_contract = operation("BenchUnfavoriteAction", None, delete=True)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Deprecation"] = "true"
        response["Sunset"] = "Wed, 01 Jul 2027 00:00:00 GMT"
        bench_id = kwargs.get("bench_id")
        if bench_id:
            response["Link"] = f'</api/labs/benches/{bench_id}/actions/favorite>; rel="successor-version"'
        return response

    def handle_post(self, request, bench_id, **kwargs):
        return self._execute(lambda: services.remove_favorite(bench_id=bench_id, actor=request.user), delete=True)


class BenchEquipmentListAPIView(BenchAPIView):
    get_contract = operation(
        "BenchEquipmentList",
        BenchSetupEquipmentSerializer,
        query=BenchEquipmentListQuerySerializer,
        many=True,
    )

    def handle_get(self, request, bench_id, **kwargs):
        filters, error = self.validate_query()
        if error is not None:
            return error

        def read():
            selectors.get_bench(bench_id=bench_id, actor=request.user)
            return selectors.list_bench_equipment(bench_id=bench_id)

        return self._execute(read)


BENCH_OPTIONS_MAX_RESULTS = 1000


class BenchSelectAPIView(OptionsAPIView):
    """Selector options for benches: unpaginated, allowlisted filters, hard cap (OPT-1 to OPT-8)."""

    query_serializer = BenchSelectQuerySerializer
    size_class = SizeClass.LARGE
    owner = "benches"
    schema_tags = ("Benches",)

    @property
    def max_results(self):
        return BENCH_OPTIONS_MAX_RESULTS

    def select(self, *, actor, filters):
        return selectors.list_bench_options(actor=actor, **filters)


class BenchGroupOptionsAPIView(OptionsAPIView):
    """Selector options for bench groups."""

    query_serializer = OptionsQueryMixin
    size_class = SizeClass.SMALL
    owner = "benches"
    schema_tags = ("Benches",)

    def select(self, *, actor, filters):
        return list_bench_group_options(actor=actor, **filters)


class BenchTypeOptionsAPIView(OptionsAPIView):
    """Selector options for bench types."""

    query_serializer = OptionsQueryMixin
    size_class = SizeClass.SMALL
    owner = "benches"
    schema_tags = ("Benches",)

    def select(self, *, actor, filters):
        return list_bench_type_options(actor=actor, **filters)


class BenchReferenceDataAPIView(BenchAPIView):
    get_contract = operation("BenchReferenceData", BenchReferenceDataSerializer)

    def handle_get(self, request, **kwargs):
        return self._execute(selectors.reference_data)


class ReferenceListCreateAPIView(BenchAPIView):
    model = None
    get_contract = operation(
        "BenchReferenceList", BenchReferenceDataSerializer, query=PageNumberQuerySerializer, many=True
    )

    def handle_get(self, request, **kwargs):
        _, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: selectors.list_references(model=self.model))

    def handle_post(self, request, **kwargs):
        return self._write(services.save_reference, lookup={"model": self.model})


class ReferenceDetailAPIView(BenchAPIView):
    model = None

    def handle_get(self, request, reference_id, **kwargs):
        return self._execute(lambda: selectors.get_reference(model=self.model, reference_id=reference_id))

    def handle_patch(self, request, reference_id, **kwargs):
        return self._write(
            services.save_reference, lookup={"model": self.model, "reference_id": reference_id}, partial=True
        )

    def handle_delete(self, request, reference_id, **kwargs):
        return self._execute(
            lambda: services.retire_reference(
                model=self.model,
                reference_id=reference_id,
                actor=request.user,
            ),
            delete=True,
        )


class BenchGroupListCreateAPIView(ReferenceListCreateAPIView):
    model = "group"
    get_contract = operation(
        "BenchGroupList", BenchGroupSerializer, query=PageNumberQuerySerializer, many=True
    )
    post_contract = operation(
        "BenchGroupCreate", BenchGroupSerializer, request=BenchReferenceWriteSerializer, created=True
    )


class BenchGroupDetailAPIView(ReferenceDetailAPIView):
    model = "group"
    get_contract = operation("BenchGroupDetail", BenchGroupSerializer)
    patch_contract = operation("BenchGroupUpdate", BenchGroupSerializer, request=BenchReferenceWriteSerializer)
    delete_contract = operation("BenchGroupRetire", None, delete=True)


class BenchTypeListCreateAPIView(ReferenceListCreateAPIView):
    model = "type"
    get_contract = operation(
        "BenchTypeList", BenchTypeSerializer, query=PageNumberQuerySerializer, many=True
    )
    post_contract = operation(
        "BenchTypeCreate", BenchTypeSerializer, request=BenchReferenceWriteSerializer, created=True
    )


class BenchTypeDetailAPIView(ReferenceDetailAPIView):
    model = "type"
    get_contract = operation("BenchTypeDetail", BenchTypeSerializer)
    patch_contract = operation("BenchTypeUpdate", BenchTypeSerializer, request=BenchReferenceWriteSerializer)
    delete_contract = operation("BenchTypeRetire", None, delete=True)
