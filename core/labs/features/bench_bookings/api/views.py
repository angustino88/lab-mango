"""Authenticated bench booking HTTP adapters; each handler calls one command or selector."""

import json
from typing import Any
from uuid import UUID

from django.core.serializers.json import DjangoJSONEncoder
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.common.api.options import OptionsAPIView, SizeClass
from core.labs.features.base import CommandAPIView, FeatureAPIView, operation
from core.labs.features.bench_bookings.application import (
    CreateBenchBookingInput,
    DecideBenchBookingApprovalInput,
    DecideBenchBookingApprovalResult,
    UpdateBenchBookingInput,
    create_bench_booking,
    decide_bench_booking_approval,
    update_bench_booking,
)
from core.labs.features.bench_bookings.queries import (
    get_bench_booking,
    get_bench_booking_by_code,
    get_lab_project,
    get_visible_bench_booking,
    get_visible_bench_booking_by_code,
    list_bench_bookings,
    list_lab_projects,
)
from core.labs.features.bench_bookings.queries.lab_projects import list_lab_project_options
from core.labs.models import BookingStatus
from core.users.public import IsLabCoordinator

from .serializers import (
    BenchBookingCancelActionSerializer,
    BenchBookingCreateSerializer,
    BenchBookingListQuerySerializer,
    BenchBookingRejectActionSerializer,
    BenchBookingSerializer,
    BenchBookingUpdateSerializer,
    LabProjectOptionsQuerySerializer,
    LabProjectQuerySerializer,
    LabProjectSerializer,
)


class BenchBookingAPIView(CommandAPIView):
    schema_tags = ("Bench Bookings",)

    def project_result(self, result):
        return get_bench_booking(booking_id=result.pk)

    def decision_body(self, booking: Any) -> dict[str, Any]:
        """Full success envelope, stored on the receipt so a replay returns identical JSON."""
        envelope = self.success_contract().respond(BenchBookingSerializer(booking).data).data
        return json.loads(json.dumps(envelope, cls=DjangoJSONEncoder))

    def decision_response(self, result: DecideBenchBookingApprovalResult) -> Response:
        response = Response(result.response_body, status=result.status_code)
        if result.replayed:
            response["Idempotency-Replayed"] = "true"
        return response


class BenchBookingCreateAPIView(AppListAPIView, BenchBookingAPIView):
    get_contract = OperationContract(
        query=BenchBookingListQuerySerializer,
        success=ResponseContract.paginated("BenchBookingList", BenchBookingSerializer),
        bad_request=ResponseContract.bad_request(),
    )
    post_contract = operation(
        "BenchBookingCreate",
        BenchBookingSerializer,
        request=BenchBookingCreateSerializer,
        created=True,
    )

    def handle_get(self, request, **kwargs):
        filters, error = self.validate_query()
        if error is not None:
            return error
        params = dict(filters or {})
        params.pop("page", None)
        params.pop("page_size", None)
        starts_at_after = params.pop("starts_at_after", None)
        starts_at_before = params.pop("starts_at_before", None)
        ordering = params.pop("ordering", None)
        return self.list_response_sync(
            list_bench_bookings(
                actor=request.user,
                starts_at_after=starts_at_after,
                starts_at_before=starts_at_before,
                ordering=ordering,
                **params,
            )
        )

    def handle_post(self, request, **kwargs):
        serializer, error = self.validate_request()
        if error is not None:
            return error
        command_input = CreateBenchBookingInput(**serializer.validated_data)
        return self._execute(
            lambda: create_bench_booking(actor=request.user, data=command_input),
            project=True,
        )


class BenchBookingDetailAPIView(BenchBookingAPIView):
    get_contract = operation("BenchBookingDetail", BenchBookingSerializer)
    patch_contract = operation(
        "BenchBookingUpdate",
        BenchBookingSerializer,
        request=BenchBookingUpdateSerializer,
        bad_request=True,
        validation_error=True,
    )

    def handle_get(self, request, booking_id, **kwargs):
        return self._execute(lambda: get_visible_bench_booking(actor=request.user, booking_id=booking_id))

    def handle_patch(self, request, booking_id, **kwargs):
        serializer, error = self.validate_request(partial=True)
        if error is not None:
            return error
        command_input = UpdateBenchBookingInput(booking_id=booking_id, fields=dict(serializer.validated_data))
        return self._execute(
            lambda: update_bench_booking(actor=request.user, data=command_input),
            project=True,
        )


class BenchBookingCancelActionAPIView(BenchBookingAPIView):
    post_contract = operation(
        "BenchBookingCancelAction",
        BenchBookingSerializer,
        request=BenchBookingCancelActionSerializer,
        bad_request=True,
        validation_error=True,
    )

    def handle_post(self, request, booking_id, **kwargs):
        serializer, error = self.validate_request()
        if error is not None:
            return error
        command_input = UpdateBenchBookingInput(
            booking_id=booking_id,
            fields={
                "status": BookingStatus.CANCELLED,
                # The payload's "reason" explains the cancellation; the booking's own
                # purpose (BenchBooking.reason) must not be overwritten.
                "cancellation_reason": serializer.validated_data.get("reason", ""),
            },
        )
        return self._execute(
            lambda: update_bench_booking(actor=request.user, data=command_input),
            project=True,
        )


class BenchBookingApproveActionAPIView(BenchBookingAPIView):
    permission_classes = [IsLabCoordinator]
    post_contract = operation(
        "BenchBookingApproveAction",
        BenchBookingSerializer,
        parameters=[
            OpenApiParameter(
                name="Idempotency-Key",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.HEADER,
                required=True,
                description=(
                    "Required UUID. A matching completed request replays its original response for 24 hours; "
                    "reuse with a different request returns 422."
                ),
            )
        ],
    )

    def handle_post(self, request, booking_id, **kwargs):
        idempotency_key, error = _idempotency_key(request)
        if error is not None:
            return error
        command_input = DecideBenchBookingApprovalInput(
            booking_id=booking_id,
            decision="approved",
            idempotency_key=idempotency_key,
        )
        return self._execute(
            lambda: decide_bench_booking_approval(
                actor=request.user,
                data=command_input,
                project_response=self.decision_body,
            ),
            project=self.decision_response,
        )


class BenchBookingRejectActionAPIView(BenchBookingAPIView):
    permission_classes = [IsLabCoordinator]
    post_contract = operation(
        "BenchBookingRejectAction",
        BenchBookingSerializer,
        request=BenchBookingRejectActionSerializer,
        bad_request=True,
        validation_error=True,
        parameters=[
            OpenApiParameter(
                name="Idempotency-Key",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.HEADER,
                required=True,
                description=(
                    "Required UUID. A matching completed request replays its original response for 24 hours; "
                    "reuse with a different request returns 422."
                ),
            )
        ],
    )

    def handle_post(self, request, booking_id, **kwargs):
        idempotency_key, key_error = _idempotency_key(request)
        if key_error is not None:
            return key_error
        serializer, error = self.validate_request()
        if error is not None:
            return error
        command_input = DecideBenchBookingApprovalInput(
            booking_id=booking_id,
            decision="rejected",
            idempotency_key=idempotency_key,
            rejection_reason=serializer.validated_data["reason"],
        )
        return self._execute(
            lambda: decide_bench_booking_approval(
                actor=request.user,
                data=command_input,
                project_response=self.decision_body,
            ),
            project=self.decision_response,
        )


def _idempotency_key(request: Request) -> tuple[str | None, Response | None]:
    key = request.headers.get("Idempotency-Key")
    if key is None:
        return None, _action_error(request, 400, "idempotency_key_required", "This action requires an Idempotency-Key header.")
    if len(key) > 64:
        return None, _action_error(request, 400, "invalid_idempotency_key", "Idempotency-Key must be a UUID.")
    try:
        parsed = UUID(key)
    except (ValueError, AttributeError):
        return None, _action_error(request, 400, "invalid_idempotency_key", "Idempotency-Key must be a UUID.")
    return str(parsed), None


def _action_error(request: Request, status_code: int, code: str, message: str) -> Response:
    from core.common.api.correlation import get_request_id

    request_id = get_request_id(request)
    return Response(
        {"error": {"code": code, "message": message, "details": [], "request_id": request_id}},
        status=status_code,
        headers={"X-Request-ID": request_id},
    )


class BenchBookingCodeDetailAPIView(BenchBookingAPIView):
    get_contract = operation("BenchBookingDetailByCode", BenchBookingSerializer)
    patch_contract = operation(
        "BenchBookingUpdateByCode",
        BenchBookingSerializer,
        request=BenchBookingUpdateSerializer,
        bad_request=True,
        validation_error=True,
    )

    def handle_get(self, request, booking_code, **kwargs):
        return self._execute(
            lambda: get_visible_bench_booking_by_code(actor=request.user, booking_code=booking_code)
        )

    def handle_patch(self, request, booking_code, **kwargs):
        serializer, error = self.validate_request(partial=True)
        if error is not None:
            return error
        booking = get_bench_booking_by_code(booking_code=booking_code)
        command_input = UpdateBenchBookingInput(booking_id=booking.pk, fields=dict(serializer.validated_data))
        return self._execute(
            lambda: update_bench_booking(actor=request.user, data=command_input),
            project=True,
        )


class BenchBookingCancelByCodeActionAPIView(BenchBookingAPIView):
    post_contract = operation(
        "BenchBookingCancelByCodeAction",
        BenchBookingSerializer,
        request=BenchBookingCancelActionSerializer,
        bad_request=True,
        validation_error=True,
    )

    def handle_post(self, request, booking_code, **kwargs):
        serializer, error = self.validate_request()
        if error is not None:
            return error
        booking = get_bench_booking_by_code(booking_code=booking_code)
        command_input = UpdateBenchBookingInput(
            booking_id=booking.pk,
            fields={
                "status": BookingStatus.CANCELLED,
                # The payload's "reason" explains the cancellation; the booking's own
                # purpose (BenchBooking.reason) must not be overwritten.
                "cancellation_reason": serializer.validated_data.get("reason", ""),
            },
        )
        return self._execute(
            lambda: update_bench_booking(actor=request.user, data=command_input),
            project=True,
        )


class LabProjectListAPIView(AppListAPIView, FeatureAPIView):
    """List the lab projects a booking can be charged to."""

    schema_tags = ("Bench Bookings",)
    get_contract = OperationContract(
        query=LabProjectQuerySerializer,
        success=ResponseContract.paginated("LabProjectList", LabProjectSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        if filters is None:
            raise TypeError("Query validation returned neither filters nor an error.")
        return self.list_response_sync(list_lab_projects(search=filters.get("search"), active=filters.get("active")))


class LabProjectOptionsAPIView(OptionsAPIView):
    """Selector options for lab projects."""

    query_serializer = LabProjectOptionsQuerySerializer
    size_class = SizeClass.LARGE
    owner = "bench_bookings"
    schema_tags = ("Bench Bookings",)

    def select(self, *, actor, filters):
        return list_lab_project_options(actor=actor, **filters)


class LabProjectDetailAPIView(FeatureAPIView):
    """Retrieve one lab project."""

    schema_tags = ("Bench Bookings",)
    get_contract = OperationContract(
        success=ResponseContract.success("LabProjectDetail", LabProjectSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, project_id: int, *args, **kwargs) -> Response:
        return self.respond(get_lab_project(project_id=project_id))


class BenchBookingCompleteActionAPIView(BenchBookingAPIView):
    post_contract = operation("BenchBookingCompleteAction", BenchBookingSerializer)

    def handle_post(self, request, booking_id, **kwargs):
        command_input = UpdateBenchBookingInput(
            booking_id=booking_id,
            fields={"status": BookingStatus.COMPLETED},
        )
        return self._execute(
            lambda: update_bench_booking(actor=request.user, data=command_input),
            project=True,
        )
