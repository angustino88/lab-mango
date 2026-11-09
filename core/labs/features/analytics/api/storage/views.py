"""Existing storage quota listing and ingestion behavior."""

from datetime import datetime

from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.request import Request
from rest_framework.response import Response

from core.labs.features.base.common import FeatureAPIView

from ...public import RecordStorageQuotaInput, list_storage_quota_measurements, record_storage_quota_measurement
from .serializers import StorageQuotaCreateSerializer, StorageQuotaListSerializer, StorageQuotaQuerySerializer


class StorageQuotaAPIView(FeatureAPIView):
    """List or ingest storage capacity utilization records."""

    schema_tags = ("Analytics",)
    get_contract = OperationContract(
        query=StorageQuotaQuerySerializer,
        success=ResponseContract.success("StorageQuotaList", StorageQuotaListSerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )
    post_contract = OperationContract(
        request=StorageQuotaCreateSerializer,
        success=ResponseContract.success("StorageQuotaCreated", StorageQuotaListSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        log_date_str = request.query_params.get("log_date")
        if not log_date_str:
            return self.respond_problem(
                "bad_request", code="missing_log_date", errors={"log_date": ["log_date is required."]}
            )
        try:
            log_date = datetime.fromisoformat(log_date_str.replace(" ", "+"))
        except ValueError:
            return self.respond_problem(
                "bad_request", code="invalid_date_format", errors={"log_date": ["Invalid ISO date format."]}
            )
        top_raw = request.query_params.get("top")
        top_n = int(top_raw) if top_raw and top_raw.isdigit() else None
        data = list_storage_quota_measurements(log_date=log_date, top_n=top_n)
        return self.respond_data(data)

    def handle_post(self, request: Request, *args, **kwargs) -> Response:
        serializer = StorageQuotaCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return self.respond_problem("bad_request", code="validation_failed", errors=serializer.errors)
        vd = serializer.validated_data
        cmd_input = RecordStorageQuotaInput(
            account_identifier=vd["account_identifier"],
            used_gibibytes=vd["used_gibibytes"],
            quota_gibibytes=vd["quota_gibibytes"],
            computer_identifier=vd.get("computer_identifier", ""),
            account_display_name=vd.get("account_display_name", ""),
            source=vd.get("source", "collector"),
        )
        measurement = record_storage_quota_measurement(cmd_input, actor=request.user)
        result = {
            "username": measurement.account_identifier,
            "account_identifier": measurement.account_identifier,
            "account_display_name": measurement.account_display_name,
            "computer_identifier": measurement.computer_identifier,
            "used": float(measurement.used_gibibytes),
            "used_gibibytes": float(measurement.used_gibibytes),
            "quota": float(measurement.quota_gibibytes),
            "quota_gibibytes": float(measurement.quota_gibibytes),
            "utilization_percent": float(measurement.utilization_percent),
            "measured_at": measurement.measured_at,
        }
        return self.respond_data(result)
