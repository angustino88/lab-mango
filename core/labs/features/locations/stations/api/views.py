"""Station HTTP mapping only; synchronous handlers use AppAPIView's async dispatch."""

from drf_api_contracts import OperationContract, ResponseContract

from core.common.api.filtering import FilterMetadataMixin, FilterMetadataSerializer
from core.common.api.options import OptionsQueryMixin, SizeClass
from core.common.api.pagination import PageNumberQuerySerializer, with_page_query
from core.labs.features.base.common import OptionsAPIView
from core.labs.features.locations.api.schema import operation
from core.labs.features.locations.api.views import LocationAPIView
from core.labs.features.locations.queries import list_station_options, list_station_type_options
from core.labs.features.locations.stations.application import services
from core.labs.features.locations.stations.queries import selectors
from core.labs.features.locations.stations.queries.summaries import get_station_status_summary

from .filters import STATION_FILTERS
from .serializers import (
    StationCreateSerializer,
    StationListQuerySerializer,
    StationOptionsQuerySerializer,
    StationPlacementSerializer,
    StationReferenceDataSerializer,
    StationSerializer,
    StationSlotCreateSerializer,
    StationSlotSerializer,
    StationSlotUpdateSerializer,
    StationStatusRecordSerializer,
    StationStatusSummarySerializer,
    StationStatusWriteSerializer,
    StationTypeSerializer,
    StationTypeWriteSerializer,
    StationUpdateSerializer,
)


class StationAPIView(LocationAPIView):
    schema_tags = ("Stations",)


def _station_projection(station):
    return selectors.get_station(station_id=station.pk)


class StationStatusSummaryAPIView(StationAPIView):
    """Non-deleted stations counted by their stored lifecycle `status`."""

    get_contract = OperationContract(
        success=ResponseContract.success("StationStatusSummaryData", StationStatusSummarySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request, **kwargs):
        if request.query_params:
            return self.respond_problem("bad_request", code="invalid_query", detail="This endpoint accepts no query parameters.")
        return self._execute(get_station_status_summary)


class StationListCreateAPIView(StationAPIView):
    get_contract = operation("StationList", StationSerializer, query=with_page_query(StationListQuerySerializer), many=True)
    post_contract = operation("StationCreate", StationSerializer, request=StationCreateSerializer, created=True)

    def handle_get(self, request, **kwargs):
        filters, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(
            lambda: STATION_FILTERS.apply(selectors.list_stations(), filters)
        )

    def handle_post(self, request, **kwargs):
        return self._write(services.create_station, project=_station_projection)


class StationFiltersAPIView(FilterMetadataMixin, StationAPIView):
    filter_spec = STATION_FILTERS
    get_contract = operation("StationFilters", FilterMetadataSerializer, query=PageNumberQuerySerializer)


class StationDetailAPIView(StationAPIView):
    get_contract = operation("StationDetail", StationSerializer)
    put_contract = operation("StationReplace", StationSerializer, request=StationUpdateSerializer)
    patch_contract = operation("StationUpdate", StationSerializer, request=StationUpdateSerializer)
    delete_contract = operation("StationDelete", None, delete=True)

    def handle_get(self, request, station_id, **kwargs):
        return self._execute(lambda: selectors.get_station(station_id=station_id))

    def handle_put(self, request, station_id, **kwargs):
        return self._write(services.update_station, lookup={"station_id": station_id}, project=_station_projection)

    def handle_patch(self, request, station_id, **kwargs):
        return self._write(
            services.update_station, lookup={"station_id": station_id}, partial=True, project=_station_projection
        )

    def handle_delete(self, request, station_id, **kwargs):
        return self._execute(lambda: services.delete_station(station_id=station_id, actor=request.user), delete=True)


class StationPlaceAPIView(StationAPIView):
    patch_contract = operation("StationPlacement", StationSerializer, request=StationPlacementSerializer)
    post_contract = operation("StationPlaceAction", StationSerializer, request=StationPlacementSerializer)

    def handle_patch(self, request, station_id, **kwargs):
        return self._write(services.place_station, lookup={"station_id": station_id}, project=_station_projection)

    def handle_post(self, request, station_id, **kwargs):
        return self._write(services.place_station, lookup={"station_id": station_id}, project=_station_projection)


class StationSlotListCreateAPIView(StationAPIView):
    get_contract = operation("StationSlotList", StationSlotSerializer, query=PageNumberQuerySerializer, many=True)
    post_contract = operation(
        "StationSlotCreate", StationSlotSerializer, request=StationSlotCreateSerializer, created=True
    )

    def handle_get(self, request, station_id, **kwargs):
        _, error = self.validate_query()
        if error is not None:
            return error
        def read():
            selectors.get_station(station_id=station_id)
            return selectors.list_station_slots(station_id=station_id)

        return self._execute(read)

    def handle_post(self, request, station_id, **kwargs):
        return self._write(services.create_station_slot, lookup={"station_id": station_id})


class StationSlotDetailAPIView(StationAPIView):
    get_contract = operation("StationSlotDetail", StationSlotSerializer)
    put_contract = operation("StationSlotReplace", StationSlotSerializer, request=StationSlotUpdateSerializer)
    patch_contract = operation("StationSlotUpdate", StationSlotSerializer, request=StationSlotUpdateSerializer)
    delete_contract = operation("StationSlotDelete", None, delete=True)

    def handle_get(self, request, station_id, slot_id, **kwargs):
        def read():
            selectors.get_station(station_id=station_id)
            return selectors.list_station_slots(station_id=station_id).get(pk=slot_id)

        return self._execute(read)

    def handle_put(self, request, station_id, slot_id, **kwargs):
        return self._write(services.update_station_slot, lookup={"station_id": station_id, "slot_id": slot_id})

    def handle_patch(self, request, station_id, slot_id, **kwargs):
        return self._write(
            services.update_station_slot, lookup={"station_id": station_id, "slot_id": slot_id}, partial=True
        )

    def handle_delete(self, request, station_id, slot_id, **kwargs):
        return self._execute(
            lambda: services.delete_station_slot(station_id=station_id, slot_id=slot_id, actor=request.user),
            delete=True,
        )


class StationStatusAPIView(StationAPIView):
    post_contract = operation(
        "StationStatusChange", StationSerializer, request=StationStatusWriteSerializer
    )

    def handle_post(self, request, station_id, **kwargs):
        serializer, error = self.validate_request()
        if error is not None:
            return error
        return self._execute(
            lambda: services.record_station_status(actor=request.user, station_id=station_id, **serializer.validated_data),
            project=lambda record: selectors.get_station(station_id=record.station_id),
        )


class StationHistoryAPIView(StationAPIView):
    get_contract = operation(
        "StationHistory", StationStatusRecordSerializer, query=PageNumberQuerySerializer, many=True
    )

    def handle_get(self, request, station_id, **kwargs):
        _, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: selectors.station_history(station_id=station_id))


class StationReferenceDataAPIView(StationAPIView):
    get_contract = operation("StationReferenceData", StationReferenceDataSerializer)

    def handle_get(self, request, **kwargs):
        return self._execute(selectors.station_reference_data)


class StationOptionsAPIView(OptionsAPIView):
    """Selector options for stations (ADR 002)."""

    query_serializer = StationOptionsQuerySerializer
    size_class = SizeClass.LARGE
    owner = "locations"
    schema_tags = ("Locations",)

    def select(self, *, actor, filters):
        return list_station_options(actor=actor, **filters)


class StationTypeOptionsAPIView(OptionsAPIView):
    """Selector options for station types (ADR 002)."""

    query_serializer = OptionsQueryMixin
    size_class = SizeClass.SMALL
    owner = "locations"
    schema_tags = ("Locations",)

    def select(self, *, actor, filters):
        return list_station_type_options(actor=actor, **filters)


class StationTypeListCreateAPIView(StationAPIView):
    get_contract = operation("StationTypeList", StationTypeSerializer, query=PageNumberQuerySerializer, many=True)
    post_contract = operation(
        "StationTypeCreate", StationTypeSerializer, request=StationTypeWriteSerializer, created=True
    )

    def handle_get(self, request, **kwargs):
        _, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(selectors.list_station_types)

    def handle_post(self, request, **kwargs):
        return self._write(services.create_station_type)


class StationTypeDetailAPIView(StationAPIView):
    get_contract = operation("StationTypeDetail", StationTypeSerializer)
    patch_contract = operation("StationTypeUpdate", StationTypeSerializer, request=StationTypeWriteSerializer)
    delete_contract = operation("StationTypeDelete", None, delete=True)

    def handle_get(self, request, type_id, **kwargs):
        return self._execute(lambda: selectors.get_station_type(type_id=type_id))

    def handle_patch(self, request, type_id, **kwargs):
        return self._write(services.update_station_type, lookup={"type_id": type_id}, partial=True)

    def handle_delete(self, request, type_id, **kwargs):
        return self._execute(lambda: services.delete_station_type(type_id=type_id, actor=request.user), delete=True)
