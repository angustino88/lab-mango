"""HTTP views for the monitoring event feature."""
from __future__ import annotations

from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.labs.features.base import CommandAPIView
from core.labs.features.monitoring import public
from core.labs.features.monitoring.api.serializers import (
    MonitoringEventCreateSerializer,
    MonitoringEventListQuerySerializer,
    MonitoringEventQuerySerializer,
    MonitoringEventSerializer,
)
from core.labs.features.monitoring.public import CreateMonitoringEventInput


def _computing_param(request: Request) -> int | None:
    """``computing_id`` filter, accepting the legacy ``computer_id`` name."""
    value = request.query_params.get("computing_id") or request.query_params.get("computer_id")
    return int(value) if value and value.isdigit() else None


class MonitoringBaseAPIView(CommandAPIView):
    """Monitoring adapters inherit the API-key-or-user policy from ``FeatureAPIView``."""


class MonitoringEventListCreateAPIView(AppListAPIView, CommandAPIView):
    """List monitoring events with pagination or record a new event."""

    schema_tags = ("Monitoring",)

    get_contract = OperationContract(
        query=MonitoringEventListQuerySerializer,
        success=ResponseContract.paginated("MonitoringEventList", MonitoringEventSerializer),
        bad_request=ResponseContract.bad_request(),
    )
    post_contract = OperationContract(
        request=MonitoringEventCreateSerializer,
        success=ResponseContract.created("MonitoringEvent", MonitoringEventSerializer),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.problem(409),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        bench_param = request.query_params.get("bench_id") or request.query_params.get("lab")
        bench_id = int(bench_param) if bench_param and bench_param.isdigit() else None
        return self._execute(
            lambda: public.list_monitoring_events(
                computer_id=_computing_param(request),
                computer_sku=request.query_params.get("computer_sku"),
                action=request.query_params.get("action") or request.query_params.get("event_type"),
                subject_type=request.query_params.get("subject_type") or request.query_params.get("category"),
                bench_id=bench_id,
                from_date=request.query_params.get("from_date") or request.query_params.get("from_date_time"),
                to_date=request.query_params.get("to_date") or request.query_params.get("to_date_time"),
            )
        )

    def handle_post(self, request: Request, *args, **kwargs) -> Response:
        serializer, error = self.validate_request(serializer_class=MonitoringEventCreateSerializer)
        if error is not None:
            return error
        command = CreateMonitoringEventInput(**serializer.validated_data)
        return self._execute(
            lambda: public.create_monitoring_event(command, actor=self.acting_user),
        )


class MonitoringEventDetailAPIView(MonitoringBaseAPIView):
    """Retrieve details of a single monitoring event."""

    schema_tags = ("Monitoring",)
    get_contract = OperationContract(
        success=ResponseContract.success("MonitoringEventDetail", MonitoringEventSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, pk: int, *args, **kwargs) -> Response:
        return self._execute(
            lambda: public.get_monitoring_event(event_id=pk),
        )


class MonitoringEventExportAPIView(MonitoringBaseAPIView):
    """Export non-paginated monitoring event list for reporting and spreadsheet download."""

    schema_tags = ("Monitoring",)
    get_contract = OperationContract(
        query=MonitoringEventQuerySerializer,
        success=ResponseContract.success("MonitoringEventExport", MonitoringEventSerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        bench_param = request.query_params.get("bench_id") or request.query_params.get("lab")
        bench_id = int(bench_param) if bench_param and bench_param.isdigit() else None
        qs = public.list_monitoring_events(
            computer_id=_computing_param(request),
            computer_sku=request.query_params.get("computer_sku"),
            action=request.query_params.get("action") or request.query_params.get("event_type"),
            subject_type=request.query_params.get("subject_type") or request.query_params.get("category"),
            bench_id=bench_id,
            from_date=request.query_params.get("from_date") or request.query_params.get("from_date_time"),
            to_date=request.query_params.get("to_date") or request.query_params.get("to_date_time"),
        )
        return self.respond(qs, many=True)


__all__ = [
    "MonitoringEventDetailAPIView",
    "MonitoringEventExportAPIView",
    "MonitoringEventListCreateAPIView",
]
