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
from core.common.api.options import SizeClass
from core.labs.features.base import (
    BENCH_BOOKING_ACCESS,
    BENCH_BOOKING_DECISION_ACCESS,
    CommandAPIView,
    FeatureAPIView,
    OptionsAPIView,
    operation,
)
from core.labs.features.bench_bookings.application import (
    CheckBenchBookingInput,
    CreateBenchBookingInput,
    DecideBenchBookingApprovalInput,
    DecideBenchBookingApprovalResult,
    IdempotentWriteResult,
    UpdateBenchBookingInput,
    check_bench_booking,
    create_bench_booking,
    decide_bench_booking_approval,
    get_bench_booking_policy,
    run_idempotent_booking_write,
    update_bench_booking,
)
from core.labs.features.bench_bookings.application.slot_watches import (
    CreateSlotWatchInput,
    cancel_slot_watch,
    create_slot_watch,
    follow_booking,
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
from core.labs.features.bench_bookings.queries.availability import list_bench_availability
from core.labs.features.bench_bookings.queries.lab_projects import list_lab_project_options
from core.labs.features.bench_bookings.queries.slot_watches import get_slot_watch, list_slot_watches
from core.labs.models import BenchBookingWriteOperation, BookingStatus

from .serializers import (
    BenchAvailabilityQuerySerializer,
    BenchAvailabilityResultSerializer,
    BenchBookingCancelActionSerializer,
    BenchBookingCheckRequestSerializer,
    BenchBookingCheckSerializer,
    BenchBookingCreateSerializer,
    BenchBookingListQuerySerializer,
    BenchBookingPolicySerializer,
    BenchBookingRejectActionSerializer,
    BenchBookingSerializer,
    BenchBookingUpdateSerializer,
    BenchSlotWatchCreateSerializer,
    BenchSlotWatchListQuerySerializer,
    BenchSlotWatchSerializer,
    LabProjectOptionsQuerySerializer,
    LabProjectQuerySerializer,
    LabProjectSerializer,
)

_OPTIONAL_IDEMPOTENCY_KEY = OpenApiParameter(
    name="Idempotency-Key",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.HEADER,
    required=False,
    description=(
        "Optional UUID. A repeat with the same key and body replays the first successful response for 24 hours "
        "(Idempotency-Replayed: true); the same key with another body or booking returns 422."
    ),
)


class BenchBookingAPIView(CommandAPIView):
    permission_classes = BENCH_BOOKING_ACCESS
    schema_tags = ("Bench Bookings",)

    def project_result(self, result):
        return get_bench_booking(booking_id=result.pk)

    def booking_write(self, *, operation: str, target: dict[str, Any], input_values: dict[str, Any], command) -> Response:
        """Run a booking write; with an Idempotency-Key header, make a repeat return the first response."""
        key, error = _optional_idempotency_key(self.request)
        if error is not None:
            return error
        if key is None:
            return self._execute(command, project=True)
        if not getattr(self.request.user, "is_authenticated", False):
            # Receipts belong to a user; API-key callers have none.
            return _action_error(
                self.request, 400, "idempotency_key_unsupported", "Idempotency-Key needs a signed-in user."
            )

        def project_response(booking) -> tuple[int, dict[str, Any]]:
            response = self.respond(self.project_result(booking))
            return response.status_code, response.data

        return self._execute(
            lambda: run_idempotent_booking_write(
                actor=self.request.user,
                operation=operation,
                key=key,
                request_values={**target, "input": input_values},
                write=command,
                project_response=project_response,
            ),
            project=self.write_response,
        )

    def write_response(self, result: IdempotentWriteResult) -> Response:
        response = self._add_created_location(Response(result.response_body, status=result.status_code))
        if result.replayed:
            response["Idempotency-Replayed"] = "true"
        return response

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
        parameters=[_OPTIONAL_IDEMPOTENCY_KEY],
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
        return self.booking_write(
            operation=BenchBookingWriteOperation.CREATE,
            target={},
            input_values=dict(serializer.validated_data),
            command=lambda: create_bench_booking(actor=request.user, data=command_input),
        )


class BenchBookingDetailAPIView(BenchBookingAPIView):
    get_contract = operation("BenchBookingDetail", BenchBookingSerializer)
    patch_contract = operation(
        "BenchBookingUpdate",
        BenchBookingSerializer,
        request=BenchBookingUpdateSerializer,
        bad_request=True,
        validation_error=True,
        parameters=[_OPTIONAL_IDEMPOTENCY_KEY],
    )

    def handle_get(self, request, booking_id, **kwargs):
        return self._execute(lambda: get_visible_bench_booking(actor=request.user, booking_id=booking_id))

    def handle_patch(self, request, booking_id, **kwargs):
        serializer, error = self.validate_request(partial=True)
        if error is not None:
            return error
        command_input = UpdateBenchBookingInput(booking_id=booking_id, fields=dict(serializer.validated_data))
        return self.booking_write(
            operation=BenchBookingWriteOperation.UPDATE,
            target={"booking_id": booking_id},
            input_values=dict(command_input.fields),
            command=lambda: update_bench_booking(actor=request.user, data=command_input),
        )


class BenchBookingCancelActionAPIView(BenchBookingAPIView):
    post_contract = operation(
        "BenchBookingCancelAction",
        BenchBookingSerializer,
        request=BenchBookingCancelActionSerializer,
        bad_request=True,
        validation_error=True,
        parameters=[_OPTIONAL_IDEMPOTENCY_KEY],
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
        return self.booking_write(
            operation=BenchBookingWriteOperation.CANCEL,
            target={"booking_id": command_input.booking_id},
            input_values=dict(command_input.fields),
            command=lambda: update_bench_booking(actor=request.user, data=command_input),
        )


class BenchBookingApproveActionAPIView(BenchBookingAPIView):
    permission_classes = BENCH_BOOKING_DECISION_ACCESS
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
    permission_classes = BENCH_BOOKING_DECISION_ACCESS
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


def _optional_idempotency_key(request: Request) -> tuple[str | None, Response | None]:
    if request.headers.get("Idempotency-Key") is None:
        return None, None
    return _idempotency_key(request)


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
        parameters=[_OPTIONAL_IDEMPOTENCY_KEY],
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
        return self.booking_write(
            operation=BenchBookingWriteOperation.UPDATE,
            target={"booking_id": booking.pk},
            input_values=dict(command_input.fields),
            command=lambda: update_bench_booking(actor=request.user, data=command_input),
        )


class BenchBookingCancelByCodeActionAPIView(BenchBookingAPIView):
    post_contract = operation(
        "BenchBookingCancelByCodeAction",
        BenchBookingSerializer,
        request=BenchBookingCancelActionSerializer,
        bad_request=True,
        validation_error=True,
        parameters=[_OPTIONAL_IDEMPOTENCY_KEY],
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
        return self.booking_write(
            operation=BenchBookingWriteOperation.CANCEL,
            target={"booking_id": command_input.booking_id},
            input_values=dict(command_input.fields),
            command=lambda: update_bench_booking(actor=request.user, data=command_input),
        )


class BenchBookingCheckActionAPIView(BenchBookingAPIView):
    """Preview a new booking, a series or a change: writes nothing, takes no locks, answers for now only."""

    post_contract = operation(
        "BenchBookingCheckAction",
        BenchBookingCheckSerializer,
        request=BenchBookingCheckRequestSerializer,
        bad_request=True,
        validation_error=True,
        forbidden=True,
    )

    def handle_post(self, request, **kwargs):
        serializer, error = self.validate_request()
        if error is not None:
            return error
        command_input = CheckBenchBookingInput(**serializer.to_command_kwargs())
        return self._execute(lambda: check_bench_booking(actor=request.user, data=command_input))


class BenchBookingPolicyAPIView(FeatureAPIView):
    """The booking rules that apply to the caller."""

    permission_classes = BENCH_BOOKING_ACCESS
    schema_tags = ("Bench Bookings",)
    get_contract = OperationContract(
        success=ResponseContract.success("BenchBookingPolicy", BenchBookingPolicySerializer),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        response = self.respond(get_bench_booking_policy(actor=request.user))
        response["Cache-Control"] = "private, max-age=300"
        return response


class BenchAvailabilityAPIView(FeatureAPIView):
    """Benches free in a window, and when the others are busy. Busy time never names who booked it."""

    permission_classes = BENCH_BOOKING_ACCESS
    schema_tags = ("Bench Bookings",)
    get_contract = OperationContract(
        query=BenchAvailabilityQuerySerializer,
        success=ResponseContract.success("BenchAvailability", BenchAvailabilityResultSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        query = BenchAvailabilityQuerySerializer.to_query_kwargs(filters)
        return self.respond(list_bench_availability(actor=request.user, **query))


class LabProjectListAPIView(AppListAPIView, FeatureAPIView):
    """List the lab projects a booking can be charged to."""
    permission_classes = BENCH_BOOKING_ACCESS

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
    permission_classes = BENCH_BOOKING_ACCESS

    query_serializer = LabProjectOptionsQuerySerializer
    size_class = SizeClass.LARGE
    owner = "bench_bookings"
    schema_tags = ("Bench Bookings",)

    def select(self, *, actor, filters):
        return list_lab_project_options(actor=actor, **filters)


class LabProjectDetailAPIView(FeatureAPIView):
    """Retrieve one lab project."""
    permission_classes = BENCH_BOOKING_ACCESS

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


class BenchSlotWatchAPIView(CommandAPIView):
    """Slot watches: the caller's own requests to hear when a bench frees up (email, Teams, web)."""

    permission_classes = BENCH_BOOKING_ACCESS
    schema_tags = ("Bench Bookings",)


class BenchSlotWatchListCreateAPIView(AppListAPIView, BenchSlotWatchAPIView):
    get_contract = OperationContract(
        query=BenchSlotWatchListQuerySerializer,
        success=ResponseContract.paginated("BenchSlotWatchList", BenchSlotWatchSerializer),
        bad_request=ResponseContract.bad_request(),
    )
    post_contract = operation(
        "BenchSlotWatchCreate",
        BenchSlotWatchSerializer,
        request=BenchSlotWatchCreateSerializer,
        created=True,
        forbidden=True,
    )

    def handle_get(self, request, **kwargs):
        filters, error = self.validate_query()
        if error is not None:
            return error
        filters = filters or {}
        return self.list_response_sync(
            list_slot_watches(
                actor=request.user, status=filters.get("status"), updated_after=filters.get("updated_after")
            )
        )

    def handle_post(self, request, **kwargs):
        serializer, error = self.validate_request()
        if error is not None:
            return error
        command_input = CreateSlotWatchInput(**serializer.to_command_kwargs())
        return self._execute(
            lambda: create_slot_watch(actor=self.acting_user, data=command_input)
        )


class BenchSlotWatchDetailAPIView(BenchSlotWatchAPIView):
    get_contract = operation("BenchSlotWatchDetail", BenchSlotWatchSerializer)

    def handle_get(self, request, watch_id, **kwargs):
        return self._execute(lambda: get_slot_watch(actor=request.user, watch_id=watch_id))


class BenchSlotWatchCancelActionAPIView(BenchSlotWatchAPIView):
    post_contract = operation("BenchSlotWatchCancelAction", BenchSlotWatchSerializer, forbidden=True)

    def handle_post(self, request, watch_id, **kwargs):
        return self._execute(lambda: cancel_slot_watch(actor=self.acting_user, watch_id=watch_id))


class BenchBookingFollowActionAPIView(BenchSlotWatchAPIView):
    """Get one alert (web, email, Teams) when this booking is about to end, completes, or is cancelled."""

    post_contract = operation("BenchBookingFollowAction", BenchSlotWatchSerializer, forbidden=True)

    def handle_post(self, request, booking_id, **kwargs):
        return self._execute(lambda: follow_booking(actor=self.acting_user, booking_id=booking_id))
