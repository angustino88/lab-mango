"""Downtime HTTP mapping only; each handler calls one command or selector."""

from core.common.api.api_views import AppListAPIView
from core.common.api.pagination import PAGE_QUERY_PARAMS, with_page_query
from core.labs.features.base import CommandAPIView, operation
from core.labs.features.downtime import queries
from core.labs.features.downtime.application import (
    ChangeDowntimeBookingAccessInput,
    DowntimeActionInput,
    ScheduleDowntimeInput,
    cancel_downtime,
    change_downtime_booking_access,
    end_downtime,
    schedule_downtime,
)

from .serializers import (
    DowntimeChangeBookingAccessSerializer,
    DowntimeCreateSerializer,
    DowntimeListQuerySerializer,
    DowntimeSerializer,
)


class DowntimeAPIView(AppListAPIView, CommandAPIView):
    """Coordinators and administrators (``LAB_OPERATIONS_ACCESS``), like every other resource write."""

    schema_tags = ("Downtime",)


def _project(window):
    return queries.get_downtime(downtime_id=window.pk)


class DowntimeListCreateAPIView(DowntimeAPIView):
    get_contract = operation(
        "DowntimeList", DowntimeSerializer, query=with_page_query(DowntimeListQuerySerializer), many=True
    )
    post_contract = operation("DowntimeCreate", DowntimeSerializer, request=DowntimeCreateSerializer, created=True)

    def handle_get(self, request, **kwargs):
        filters, error = self.validate_query()
        if error is not None:
            return error
        # ``page`` and ``page_size`` are validated with the query but belong to the paginator, not the selector.
        selector_filters = {key: value for key, value in (filters or {}).items() if key not in PAGE_QUERY_PARAMS}
        return self._execute(lambda: queries.list_downtimes(**selector_filters))

    def handle_post(self, request, **kwargs):
        serializer, error = self.validate_request()
        if error is not None:
            return error
        command = ScheduleDowntimeInput(**(serializer.validated_data if serializer is not None else {}))
        return self._execute(lambda: schedule_downtime(command, actor=self.acting_user), project=_project)


class DowntimeDetailAPIView(DowntimeAPIView):
    get_contract = operation("DowntimeDetail", DowntimeSerializer)

    def handle_get(self, request, downtime_id, **kwargs):
        return self._execute(lambda: queries.get_downtime(downtime_id=downtime_id))


class DowntimeEndAPIView(DowntimeAPIView):
    post_contract = operation("DowntimeEnd", DowntimeSerializer)

    def handle_post(self, request, downtime_id, **kwargs):
        return self._execute(
            lambda: end_downtime(DowntimeActionInput(downtime_id), actor=self.acting_user), project=_project
        )


class DowntimeCancelAPIView(DowntimeAPIView):
    post_contract = operation("DowntimeCancel", DowntimeSerializer)

    def handle_post(self, request, downtime_id, **kwargs):
        return self._execute(
            lambda: cancel_downtime(DowntimeActionInput(downtime_id), actor=self.acting_user), project=_project
        )


class DowntimeChangeBookingAccessAPIView(DowntimeAPIView):
    """Open the window to lab operator bookings (``lab_operators``) or close it to everyone (``closed``)."""

    post_contract = operation(
        "DowntimeChangeBookingAccess", DowntimeSerializer, request=DowntimeChangeBookingAccessSerializer
    )

    def handle_post(self, request, downtime_id, **kwargs):
        serializer, error = self.validate_request()
        if error is not None:
            return error
        data = serializer.validated_data if serializer is not None else {}
        command = ChangeDowntimeBookingAccessInput(downtime_id=downtime_id, **data)
        return self._execute(lambda: change_downtime_booking_access(command, actor=self.acting_user), project=_project)


__all__ = [
    "DowntimeCancelAPIView",
    "DowntimeChangeBookingAccessAPIView",
    "DowntimeDetailAPIView",
    "DowntimeEndAPIView",
    "DowntimeListCreateAPIView",
]
