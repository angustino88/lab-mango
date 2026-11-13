"""Room HTTP mapping only; synchronous handlers use AppAPIView's async dispatch."""

from drf_api_contracts import OperationContract, ResponseContract

from core.common.api.filtering import FilterMetadataMixin, FilterMetadataSerializer
from core.common.api.options import SizeClass
from core.common.api.pagination import PageNumberQuerySerializer, with_page_query
from core.labs.features.base.common import OptionsAPIView
from core.labs.features.locations.api.schema import operation
from core.labs.features.locations.api.views import LocationAPIView
from core.labs.features.locations.queries import list_room_options
from core.labs.features.locations.rooms.application import services
from core.labs.features.locations.rooms.queries import selectors
from core.labs.features.locations.rooms.queries.summaries import get_room_status_summary

from .filters import ROOM_FILTERS
from .serializers import (
    RoomCreateSerializer,
    RoomLifecycleWriteSerializer,
    RoomListQuerySerializer,
    RoomObservationSerializer,
    RoomObservationWriteSerializer,
    RoomOptionsQuerySerializer,
    RoomSerializer,
    RoomSlotSerializer,
    RoomStatusRecordSerializer,
    RoomStatusSummarySerializer,
    RoomStatusWriteSerializer,
    RoomUpdateSerializer,
)


class RoomAPIView(LocationAPIView):
    schema_tags = ("Rooms",)


def _room_projection(room):
    return selectors.get_room(room_id=room.pk)


class RoomStatusSummaryAPIView(RoomAPIView):
    """Non-deleted rooms counted by their stored lifecycle `status`."""

    get_contract = OperationContract(
        success=ResponseContract.success("RoomStatusSummaryData", RoomStatusSummarySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request, **kwargs):
        if request.query_params:
            return self.respond_problem("bad_request", code="invalid_query", detail="This endpoint accepts no query parameters.")
        return self._execute(get_room_status_summary)


class RoomListCreateAPIView(RoomAPIView):
    get_contract = operation("RoomList", RoomSerializer, query=with_page_query(RoomListQuerySerializer), many=True)
    post_contract = operation("RoomCreate", RoomSerializer, request=RoomCreateSerializer, created=True)

    def handle_get(self, request, **kwargs):
        filters, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: ROOM_FILTERS.apply(selectors.list_rooms(), filters))

    def handle_post(self, request, **kwargs):
        return self._write(services.create_room, project=_room_projection)


class RoomFiltersAPIView(FilterMetadataMixin, RoomAPIView):
    filter_spec = ROOM_FILTERS
    get_contract = operation("RoomFilters", FilterMetadataSerializer, query=PageNumberQuerySerializer)


class RoomOptionsAPIView(OptionsAPIView):
    """Selector options for rooms (ADR 002)."""

    query_serializer = RoomOptionsQuerySerializer
    size_class = SizeClass.LARGE
    owner = "locations"
    schema_tags = ("Locations",)

    def select(self, *, actor, filters):
        return list_room_options(actor=actor, **filters)


class RoomDetailAPIView(RoomAPIView):
    get_contract = operation("RoomDetail", RoomSerializer)
    put_contract = operation("RoomReplace", RoomSerializer, request=RoomUpdateSerializer)
    patch_contract = operation("RoomUpdate", RoomSerializer, request=RoomUpdateSerializer)
    delete_contract = operation("RoomDelete", None, delete=True)

    def handle_get(self, request, room_id, **kwargs):
        return self._execute(lambda: selectors.get_room(room_id=room_id))

    def handle_put(self, request, room_id, **kwargs):
        return self._write(services.update_room, lookup={"room_id": room_id}, project=_room_projection)

    def handle_patch(self, request, room_id, **kwargs):
        return self._write(services.update_room, lookup={"room_id": room_id}, partial=True, project=_room_projection)

    def handle_delete(self, request, room_id, **kwargs):
        return self._execute(lambda: services.delete_room(room_id=room_id, actor=request.user), delete=True)


class RoomSlotListAPIView(RoomAPIView):
    get_contract = operation("RoomSlotList", RoomSlotSerializer, query=PageNumberQuerySerializer, many=True)

    def handle_get(self, request, room_id, **kwargs):
        _, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: selectors.list_room_slots(room_id=room_id))


class RoomSlotGenerateAPIView(RoomAPIView):
    post_contract = operation("RoomSlotGenerate", RoomSlotSerializer, many=True)

    def handle_post(self, request, room_id, **kwargs):
        return self._execute(
            lambda: services.generate_room_slots(room_id=room_id, actor=request.user),
            project=lambda room: selectors.list_room_slots(room_id=room.pk),
        )


class RoomLifecycleAPIView(RoomAPIView):
    """Set ``lifecycle_status`` and/or ``access_policy``. Downtime is recorded at ``/api/labs/downtimes``."""

    post_contract = operation("RoomLifecycleChange", RoomSerializer, request=RoomLifecycleWriteSerializer)

    def handle_post(self, request, room_id, **kwargs):
        return self._write(
            services.change_room_lifecycle,
            lookup={"room_id": room_id},
            project=_room_projection,
        )


class RoomStatusAPIView(RoomAPIView):
    post_contract = operation(
        "RoomStatusChange",
        RoomSerializer,
        request=RoomStatusWriteSerializer,
    )

    def handle_post(self, request, room_id, **kwargs):
        serializer, error = self.validate_request()
        if error is not None:
            return error
        return self._execute(
            lambda: services.record_room_status(
                actor=request.user,
                room_id=room_id,
                **serializer.validated_data,
            ),
            project=lambda record: selectors.get_room(room_id=record.room_id),
        )


class RoomHistoryAPIView(RoomAPIView):
    get_contract = operation("RoomHistory", RoomStatusRecordSerializer, query=PageNumberQuerySerializer, many=True)

    def handle_get(self, request, room_id, **kwargs):
        _, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: selectors.room_status_history(room_id=room_id))


class RoomObservationListCreateAPIView(RoomAPIView):
    get_contract = operation(
        "RoomObservationList", RoomObservationSerializer, query=PageNumberQuerySerializer, many=True
    )
    post_contract = operation(
        "RoomObservationCreate",
        RoomObservationSerializer,
        request=RoomObservationWriteSerializer,
        created=True,
        bad_request=True,
        validation_error=True,
    )

    def handle_get(self, request, room_id, **kwargs):
        _, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: selectors.room_observations(room_id=room_id))

    def handle_post(self, request, room_id, **kwargs):
        serializer, error = self.validate_request()
        if error is not None:
            return error
        return self._execute(
            lambda: services.record_room_observation(room_id=room_id, **serializer.validated_data),
        )
