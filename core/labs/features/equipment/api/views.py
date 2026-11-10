"""Contract-based API views for redesigned equipment resources."""

from typing import Any, ClassVar

from asgiref.sync import sync_to_async
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.common.api.filtering import FilterMetadataMixin, FilterMetadataSerializer
from core.common.api.options import OptionsAPIView, OptionsQueryMixin, SizeClass
from core.common.api.pagination import PageNumberQuerySerializer, ResultsSetPagination
from core.labs.features.equipment.api.serializers import (
    EquipmentCategorySerializer,
    EquipmentKindSerializer,
    EquipmentManufacturerSerializer,
    EquipmentProductModelSerializer,
    EquipmentTypeSerializer,
)
from core.labs.features.equipment.application import (
    AssignEquipmentInput,
    CancelReservationInput,
    ChangeConditionInput,
    ChangeLifecycleInput,
    CreateEquipmentInput,
    ExtendLoanInput,
    ExtendLoansInput,
    HandOverEquipmentInput,
    HandOverReservationInput,
    LendEquipmentBatchInput,
    PlaceEquipmentInput,
    RemovePlacementInput,
    ReserveEquipmentBatchInput,
    ReturnEquipmentBatchInput,
    ReturnEquipmentInput,
    UnassignEquipmentInput,
    UpdateReservationInput,
    assign_equipment,
    cancel_reservation,
    change_condition,
    change_lifecycle,
    create_equipment,
    extend_loan,
    extend_loans,
    hand_over_equipment,
    hand_over_reservation,
    lend_equipment_batch,
    place_equipment,
    remove_placement,
    reserve_equipment_batch,
    return_equipment,
    return_equipment_batch,
    unassign_equipment,
    update_reservation,
)
from core.labs.features.equipment.exceptions import LoanIdempotencyKeyRequired
from core.labs.features.equipment.queries import (
    category_options_queryset,
    equipment_reference_data,
    get_active_equipment_assignment,
    get_equipment,
    list_equipment,
    list_equipment_options,
)
from core.labs.features.equipment.queries.loans import get_active_loan, get_loan_batch, list_loans
from core.labs.features.equipment.queries.placements import get_active_placement
from core.labs.features.equipment.queries.reference_data import (
    get_department,
    get_equipment_category,
    get_equipment_kind,
    get_equipment_manufacturer,
    get_equipment_product_model,
    get_equipment_type,
    get_resource_group,
    list_department_options,
    list_departments,
    list_equipment_categories,
    list_equipment_category_options,
    list_equipment_kind_options,
    list_equipment_kinds,
    list_equipment_manufacturer_options,
    list_equipment_manufacturers,
    list_equipment_product_model_options,
    list_equipment_product_models,
    list_equipment_type_options,
    list_equipment_types,
    list_resource_group_options,
    list_resource_groups,
)
from core.labs.features.equipment.queries.reservations import list_reservations
from core.labs.models import Equipment
from core.labs.models.resource.equipment.assignment import EquipmentAssignment

from ..queries.summaries import (
    get_computing_activity_summary,
    get_equipment_category_status_summary,
    get_equipment_status_summary,
)
from .common import EQUIPMENT_PERMISSIONS, ORGANIZATION_PERMISSIONS, EquipmentAPIView
from .resource_filters import EQUIPMENT_FILTERS
from .serializers import (
    CategoryOptionsQuerySerializer,
    ComputingActivitySummarySerializer,
    DepartmentSerializer,
    EquipmentAssignmentResultSerializer,
    EquipmentAssignmentSerializer,
    EquipmentChangeConditionSerializer,
    EquipmentChangeLifecycleSerializer,
    EquipmentCreateSerializer,
    EquipmentExtendLoanSerializer,
    EquipmentExtendLoansSerializer,
    EquipmentHandOverSerializer,
    EquipmentKindOptionsQuerySerializer,
    EquipmentLendBatchSerializer,
    EquipmentLoanBatchSerializer,
    EquipmentLoanListQuerySerializer,
    EquipmentLoanSerializer,
    EquipmentManufacturerOptionsQuerySerializer,
    EquipmentOptionsQuerySerializer,
    EquipmentPlacementSerializer,
    EquipmentPlacementWriteSerializer,
    EquipmentProductModelOptionsQuerySerializer,
    EquipmentReferenceDataSerializer,
    EquipmentReservationCancelSerializer,
    EquipmentReservationHandOverSerializer,
    EquipmentReservationListQuerySerializer,
    EquipmentReservationSerializer,
    EquipmentReservationUpdateSerializer,
    EquipmentReserveSerializer,
    EquipmentReturnBatchSerializer,
    EquipmentReturnSerializer,
    EquipmentSerializer,
    EquipmentStatusSummarySerializer,
    EquipmentTypeOptionsQuerySerializer,
    ResourceGroupCatalogSerializer,
    ResourceGroupOptionsQuerySerializer,
)

EquipmentListQuerySerializer = EQUIPMENT_FILTERS.serializer("EquipmentListQuerySerializer")


class EquipmentStatusSummaryAPIView(EquipmentAPIView):
    """Non-deleted equipment by latest recorded lifecycle status; no filters."""

    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentStatusSummaryData", EquipmentStatusSummarySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        if request.query_params:
            return self.respond_problem(
                "bad_request", code="invalid_query", detail="This endpoint accepts no query parameters."
            )
        return self.respond(get_equipment_status_summary())


class ComputingActivitySummaryAPIView(EquipmentAPIView):
    """All non-deleted computing assets by stored activity; missing telemetry is unknown."""

    permission_classes = ORGANIZATION_PERMISSIONS
    get_contract = OperationContract(
        success=ResponseContract.success("ComputingActivitySummaryData", ComputingActivitySummarySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        if request.query_params:
            return self.respond_problem(
                "bad_request", code="invalid_query", detail="This endpoint accepts no query parameters."
            )
        return self.respond(get_computing_activity_summary())


class EquipmentCategorySummaryAPIView(EquipmentAPIView):
    """Summary of one equipment subtype, configured by category route generation."""

    category_key = None
    category_model = None

    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentCategoryStatusSummaryData", EquipmentStatusSummarySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        if request.query_params:
            return self.respond_problem(
                "bad_request", code="invalid_query", detail="This endpoint accepts no query parameters."
            )
        if self.category_model is None:
            raise TypeError("Equipment category summary view must define category_model")
        return self.respond(get_equipment_category_status_summary(equipment_model=self.category_model))


class EquipmentListAPIView(AppListAPIView, EquipmentAPIView):
    """Paginated response adapter for the generic equipment collection."""

    pagination_class = ResultsSetPagination
    get_contract = OperationContract(
        query=EquipmentListQuerySerializer,
        success=ResponseContract.paginated("EquipmentList", EquipmentSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        queryset = EQUIPMENT_FILTERS.apply(list_equipment(), filters)
        return self.list_response_sync(queryset)


class EquipmentFiltersAPIView(FilterMetadataMixin, EquipmentAPIView):
    filter_spec = EQUIPMENT_FILTERS
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.success("EquipmentFilters", FilterMetadataSerializer),
    )


class EquipmentListCreateAPIView(EquipmentListAPIView):
    """List equipment with filters, or create a base equipment record."""

    post_contract = OperationContract(
        request=EquipmentCreateSerializer,
        success=ResponseContract.created("EquipmentCreate", EquipmentSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
    )

    def handle_post(self, request: Request, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        equipment = create_equipment(
            CreateEquipmentInput(fields=tuple(serializer.validated_data.items())),
            actor=request.user,
        )
        return self.respond(equipment)


class EquipmentRetrieveAPIView(EquipmentAPIView):
    """Retrieve one equipment record."""

    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentDetail", EquipmentSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        return self.respond(get_equipment(equipment_id))


class EquipmentAssignmentAPIView(EquipmentAPIView):
    """Assign equipment to a bench, or release its current assignment."""

    post_contract = OperationContract(
        request=EquipmentAssignmentSerializer,
        success=ResponseContract.success("EquipmentAssignment", EquipmentAssignmentResultSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
    )
    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentAssignmentDetail", EquipmentAssignmentResultSerializer),
        not_found=ResponseContract.not_found(),
    )
    delete_contract = OperationContract(
        success=ResponseContract.no_content(),
        not_found=ResponseContract.not_found(),
    )

    def handle_post(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        assignment = assign_equipment(
            AssignEquipmentInput(
                equipment_id=equipment_id,
                bench_id=serializer.validated_data["bench_id"],
                role=serializer.validated_data["role"],
                position=serializer.validated_data["position"],
            ),
            actor=request.user,
        )
        return self.respond(assignment)

    async def get(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        try:
            assignment = await sync_to_async(get_active_equipment_assignment)(equipment_id=equipment_id)
        except EquipmentAssignment.DoesNotExist:
            return self.respond_problem("not_found")
        data = EquipmentAssignmentResultSerializer(assignment, context={"request": request}).data
        return self.respond_data(data)

    async def delete(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        try:
            await sync_to_async(unassign_equipment)(UnassignEquipmentInput(equipment_id), actor=request.user)
        except Equipment.DoesNotExist:
            return self.respond_problem("not_found")
        return Response(status=status.HTTP_204_NO_CONTENT)


class EquipmentPlacementAPIView(EquipmentAPIView):
    """Where a unit is: on a bench, at a station, in a room, or at an untracked place.

    ``/assignment`` keeps showing bench placements only; this route shows every kind.
    """

    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentPlacementDetail", EquipmentPlacementSerializer),
        not_found=ResponseContract.not_found(),
    )
    put_contract = OperationContract(
        request=EquipmentPlacementWriteSerializer,
        success=ResponseContract.success("EquipmentPlacementUpdated", EquipmentPlacementSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
    )
    delete_contract = OperationContract(
        success=ResponseContract.no_content(),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        return self.respond(get_active_placement(equipment_id=equipment_id))

    def handle_put(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        if serializer is None:
            raise TypeError("Request validation returned no serializer.")
        data = serializer.validated_data
        place_equipment(
            PlaceEquipmentInput(
                equipment_id=equipment_id,
                bench_id=data["bench_id"],
                station_id=data["station_id"],
                room_id=data["room_id"],
                location_note=data["location_note"],
                role=data["role"],
                position=data["position"],
            ),
            actor=self.acting_user,
        )
        return self.respond(get_active_placement(equipment_id=equipment_id))

    def handle_delete(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        remove_placement(RemovePlacementInput(equipment_id=equipment_id), actor=self.acting_user)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    get=extend_schema(
        deprecated=True,
        description="Deprecated alias for equipment assignment. Use /api/labs/equipment/{equipment_id}/assignment instead.",
    ),
    post=extend_schema(
        deprecated=True,
        description="Deprecated alias for equipment assignment. Use /api/labs/equipment/{equipment_id}/assignment instead.",
    ),
    delete=extend_schema(
        deprecated=True,
        description="Deprecated alias for equipment assignment. Use /api/labs/equipment/{equipment_id}/assignment instead.",
    ),
)
class DeprecatedEquipmentAssignmentActionAPIView(EquipmentAssignmentAPIView):
    """Deprecated alias for equipment assignment.

    Use /api/labs/equipment/{equipment_id}/assignment instead.
    """

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Deprecation"] = "true"
        response["Sunset"] = "Wed, 01 Jul 2027 00:00:00 GMT"
        equipment_id = kwargs.get("equipment_id")
        if equipment_id:
            response["Link"] = f'</api/labs/equipment/{equipment_id}/assignment>; rel="successor-version"'
        return response


class EquipmentLoanAPIView(EquipmentAPIView):
    """The unit's open loan; 404 when nobody holds it."""

    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentLoanDetail", EquipmentLoanSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        return self.respond(get_active_loan(equipment_id=equipment_id))


def _loan_contract(name: str, request: Any) -> OperationContract:
    return OperationContract(
        request=request,
        success=ResponseContract.success(name, EquipmentLoanSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
    )


class EquipmentHandOverAPIView(EquipmentAPIView):
    """Hand an available unit to a person until ``due_at``; it leaves its resting place."""

    post_contract = _loan_contract("EquipmentLoanOpened", EquipmentHandOverSerializer)

    def handle_post(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        if serializer is None:
            raise TypeError("Request validation returned no serializer.")
        data = serializer.validated_data
        loan = hand_over_equipment(
            HandOverEquipmentInput(
                equipment_id=equipment_id,
                borrower_id=data["borrower_id"],
                borrower_name=data["borrower_name"],
                borrower_contact=data["borrower_contact"],
                purpose=data["purpose"],
                due_at=data["due_at"],
                condition_out=data["condition_out"],
            ),
            actor=self.acting_user,
        )
        return self.respond(get_active_loan(equipment_id=loan.equipment_id))


class EquipmentReturnAPIView(EquipmentAPIView):
    """Take a unit back; optionally record its condition and where it now is."""

    post_contract = _loan_contract("EquipmentLoanClosed", EquipmentReturnSerializer)

    def handle_post(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        if serializer is None:
            raise TypeError("Request validation returned no serializer.")
        data = serializer.validated_data
        loan = return_equipment(ReturnEquipmentInput(equipment_id=equipment_id, **data), actor=self.acting_user)
        return self.respond(list_loans().get(pk=loan.pk))


class EquipmentExtendLoanAPIView(EquipmentAPIView):
    """Move the due time of a loan that is not tied to a booking."""

    post_contract = _loan_contract("EquipmentLoanExtended", EquipmentExtendLoanSerializer)

    def handle_post(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        if serializer is None:
            raise TypeError("Request validation returned no serializer.")
        loan = extend_loan(
            ExtendLoanInput(equipment_id=equipment_id, due_at=serializer.validated_data["due_at"]),
            actor=self.acting_user,
        )
        return self.respond(list_loans().get(pk=loan.pk))


class EquipmentLoanListCreateAPIView(AppListAPIView, EquipmentAPIView):
    """List loan lines, or hand several items to one borrower in one all-or-nothing request."""

    pagination_class = ResultsSetPagination
    get_contract = OperationContract(
        query=EquipmentLoanListQuerySerializer,
        success=ResponseContract.paginated("EquipmentLoanList", EquipmentLoanSerializer),
        bad_request=ResponseContract.bad_request(),
    )
    post_contract = OperationContract(
        request=EquipmentLendBatchSerializer,
        success=ResponseContract.created("EquipmentLoanBatchCreated", EquipmentLoanBatchSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        conflict=ResponseContract.conflict(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        filters = {key: value for key, value in (filters or {}).items() if key not in {"page", "page_size"}}
        return self.list_response_sync(list_loans(**filters))

    def handle_post(self, request: Request, *args, **kwargs) -> Response:
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            raise LoanIdempotencyKeyRequired()
        serializer, error = self.validate_request()
        if error is not None:
            return error
        if serializer is None:
            raise TypeError("Request validation returned no serializer.")
        data = serializer.validated_data
        batch = lend_equipment_batch(
            LendEquipmentBatchInput(
                equipment_ids=tuple(data["equipment_ids"]),
                due_at=data["due_at"],
                borrower_id=data["borrower_id"],
                borrower_name=data["borrower_name"],
                borrower_contact=data["borrower_contact"],
                purpose=data["purpose"],
                conditions_out=tuple((item["equipment_id"], item["condition_out"]) for item in data["items"]),
                idempotency_key=key,
            ),
            actor=self.acting_user,
        )
        return self.respond(get_loan_batch(batch_id=batch.pk))


class EquipmentLoanBatchAPIView(EquipmentAPIView):
    """One loan slip with all its lines."""

    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentLoanBatchDetail", EquipmentLoanBatchSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, batch_id: int, *args, **kwargs) -> Response:
        return self.respond(get_loan_batch(batch_id=batch_id))


def _loan_lines_contract(name: str, request: Any) -> OperationContract:
    return OperationContract(
        request=request,
        success=ResponseContract.success(name, EquipmentLoanSerializer, many=True),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        conflict=ResponseContract.conflict(),
    )


class EquipmentLoanReturnBatchAPIView(EquipmentAPIView):
    """Take several items back (any subset of what is out); all or nothing."""

    post_contract = _loan_lines_contract("EquipmentLoansReturned", EquipmentReturnBatchSerializer)

    def handle_post(self, request: Request, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        if serializer is None:
            raise TypeError("Request validation returned no serializer.")
        items = tuple(ReturnEquipmentInput(**item) for item in serializer.validated_data["items"])
        loans = return_equipment_batch(ReturnEquipmentBatchInput(items=items), actor=self.acting_user)
        return self.respond(list(list_loans().filter(pk__in=[loan.pk for loan in loans])), many=True)


class EquipmentLoanExtendBatchAPIView(EquipmentAPIView):
    """Move the due time of several open loans: listed items, or every open line of a slip."""

    post_contract = _loan_lines_contract("EquipmentLoansExtended", EquipmentExtendLoansSerializer)

    def handle_post(self, request: Request, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        if serializer is None:
            raise TypeError("Request validation returned no serializer.")
        data = serializer.validated_data
        loans = extend_loans(
            ExtendLoansInput(
                due_at=data["due_at"], equipment_ids=tuple(data["equipment_ids"]), batch_id=data["batch_id"]
            ),
            actor=self.acting_user,
        )
        return self.respond(list(list_loans().filter(pk__in=[loan.pk for loan in loans])), many=True)


class EquipmentReservationListCreateAPIView(AppListAPIView, EquipmentAPIView):
    """List reservation lines, or reserve several items for one borrower and window (all or nothing)."""

    pagination_class = ResultsSetPagination
    get_contract = OperationContract(
        query=EquipmentReservationListQuerySerializer,
        success=ResponseContract.paginated("EquipmentReservationList", EquipmentReservationSerializer),
        bad_request=ResponseContract.bad_request(),
    )
    post_contract = OperationContract(
        request=EquipmentReserveSerializer,
        success=ResponseContract.created("EquipmentReservationCreated", EquipmentLoanBatchSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        conflict=ResponseContract.conflict(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        filters = {key: value for key, value in (filters or {}).items() if key not in {"page", "page_size"}}
        return self.list_response_sync(list_reservations(**filters))

    def handle_post(self, request: Request, *args, **kwargs) -> Response:
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            raise LoanIdempotencyKeyRequired()
        serializer, error = self.validate_request()
        if error is not None:
            return error
        if serializer is None:
            raise TypeError("Request validation returned no serializer.")
        data = serializer.validated_data
        batch = reserve_equipment_batch(
            ReserveEquipmentBatchInput(
                equipment_ids=tuple(data["equipment_ids"]),
                starts_at=data["starts_at"],
                ends_at=data["ends_at"],
                borrower_id=data["borrower_id"],
                borrower_name=data["borrower_name"],
                borrower_contact=data["borrower_contact"],
                purpose=data["purpose"],
                idempotency_key=key,
            ),
            actor=self.acting_user,
        )
        return self.respond(get_loan_batch(batch_id=batch.pk))


class EquipmentReservationDetailAPIView(EquipmentAPIView):
    """One reservation slip with its lines; PATCH moves the window, adds or drops items."""

    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentReservationDetail", EquipmentLoanBatchSerializer),
        not_found=ResponseContract.not_found(),
    )
    patch_contract = OperationContract(
        request=EquipmentReservationUpdateSerializer,
        success=ResponseContract.success("EquipmentReservationUpdated", EquipmentLoanBatchSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
    )

    def handle_get(self, request: Request, batch_id: int, *args, **kwargs) -> Response:
        return self.respond(get_loan_batch(batch_id=batch_id))

    def handle_patch(self, request: Request, batch_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        if serializer is None:
            raise TypeError("Request validation returned no serializer.")
        data = serializer.validated_data
        update_reservation(
            UpdateReservationInput(
                batch_id=batch_id,
                starts_at=data["starts_at"],
                ends_at=data["ends_at"],
                add_equipment_ids=tuple(data["add_equipment_ids"]),
                remove_equipment_ids=tuple(data["remove_equipment_ids"]),
            ),
            actor=self.acting_user,
        )
        return self.respond(get_loan_batch(batch_id=batch_id))


def _reservation_action_contract(name: str, request: Any) -> OperationContract:
    return OperationContract(
        request=request,
        success=ResponseContract.success(name, EquipmentLoanBatchSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
    )


class EquipmentReservationCancelAPIView(EquipmentAPIView):
    """Cancel the reserved lines of a slip (all, or the listed items) with a reason."""

    post_contract = _reservation_action_contract("EquipmentReservationCancelled", EquipmentReservationCancelSerializer)

    def handle_post(self, request: Request, batch_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        if serializer is None:
            raise TypeError("Request validation returned no serializer.")
        data = serializer.validated_data
        cancel_reservation(
            CancelReservationInput(
                batch_id=batch_id, reason=data["reason"], equipment_ids=tuple(data["equipment_ids"])
            ),
            actor=self.acting_user,
        )
        return self.respond(get_loan_batch(batch_id=batch_id))


class EquipmentReservationHandOverAPIView(EquipmentAPIView):
    """Hand over reserved items (all, or the listed ones); each loan is due at the reservation end."""

    post_contract = _reservation_action_contract(
        "EquipmentReservationHandedOver", EquipmentReservationHandOverSerializer
    )

    def handle_post(self, request: Request, batch_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        if serializer is None:
            raise TypeError("Request validation returned no serializer.")
        data = serializer.validated_data
        hand_over_reservation(
            HandOverReservationInput(
                batch_id=batch_id,
                equipment_ids=tuple(data["equipment_ids"]),
                conditions_out=tuple((item["equipment_id"], item["condition_out"]) for item in data["items"]),
            ),
            actor=self.acting_user,
        )
        return self.respond(get_loan_batch(batch_id=batch_id))


class EquipmentStateActionAPIView(EquipmentAPIView):
    """Change a unit's condition or lifecycle state; responds with the updated equipment.

    Category routes set ``queryset_provider`` so a unit of another category is 404.
    """

    action: ClassVar[str] = ""
    queryset_provider: Any = None

    def handle_post(
        self, request: Request, equipment_id: int | None = None, pk: int | None = None, *args, **kwargs
    ) -> Response:
        target_id = equipment_id if equipment_id is not None else pk
        provider = type(self).queryset_provider
        visible = provider() if provider is not None else list_equipment()
        if target_id is None or not visible.filter(pk=target_id).exists():
            return self.respond_problem("not_found")
        serializer, error = self.validate_request()
        if error is not None:
            return error
        if serializer is None:
            raise TypeError("Request validation returned no serializer.")
        data = serializer.validated_data
        if self.action == "condition":
            change_condition(
                ChangeConditionInput(equipment_id=target_id, condition=data["condition"], reason=data["reason"]),
                actor=self.acting_user,
            )
        elif self.action == "lifecycle":
            change_lifecycle(
                ChangeLifecycleInput(
                    equipment_id=target_id,
                    lifecycle_state=data["lifecycle_state"],
                    reason=data["reason"],
                    receiving_organisation=data["receiving_organisation"],
                    transfer_date=data["transfer_date"],
                ),
                actor=self.acting_user,
            )
        else:
            raise TypeError(f"{type(self).__name__} must set action to 'condition' or 'lifecycle'.")
        return self.respond(visible.get(pk=target_id))


def state_action_contract(action: str, response_name: str, detail_serializer: Any, **extra: Any) -> OperationContract:
    request = EquipmentChangeConditionSerializer if action == "condition" else EquipmentChangeLifecycleSerializer
    return OperationContract(
        request=request,
        success=ResponseContract.success(response_name, detail_serializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
        **extra,
    )


class EquipmentChangeConditionAPIView(EquipmentStateActionAPIView):
    """Set whether an in-service unit works (operational, in maintenance, out of service)."""

    action = "condition"
    post_contract = state_action_contract("condition", "EquipmentDetailAfterConditionChange", EquipmentSerializer)


class EquipmentChangeLifecycleAPIView(EquipmentStateActionAPIView):
    """Move a unit along its lifecycle (planned, in service, transferred out, retired, lost)."""

    action = "lifecycle"
    post_contract = state_action_contract("lifecycle", "EquipmentDetailAfterLifecycleChange", EquipmentSerializer)


class EquipmentReferenceDataAPIView(EquipmentAPIView):
    """Generic equipment lookups. Computing-specific lookups live under computing/."""

    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentReferenceData", EquipmentReferenceDataSerializer),
        unauthorized=ResponseContract.unauthorized(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        references = equipment_reference_data()
        data = {
            "categories": EquipmentCategorySerializer(references["categories"], many=True).data,
            "kinds": EquipmentKindSerializer(references["kinds"], many=True).data,
            "types": EquipmentTypeSerializer(references["types"], many=True).data,
            "manufacturers": EquipmentManufacturerSerializer(references["manufacturers"], many=True).data,
            "product_models": EquipmentProductModelSerializer(references["product_models"], many=True).data,
        }
        return self.respond_data(data)


class EquipmentOptionsAPIView(OptionsAPIView):
    """List equipment as compact options, optionally filtering for assignable items (ADR 002)."""

    permission_classes = EQUIPMENT_PERMISSIONS
    schema_description = (
        "Large Equipment selectors require q or at least one declared parent filter: category_id, kind_id, "
        "type_id, or manufacturer_id. include_ids, lifecycle_status, assigned, and assignable do not satisfy "
        "this requirement."
    )
    query_serializer = EquipmentOptionsQuerySerializer
    size_class = SizeClass.LARGE
    required_any = (
        "q",
        "category_id",
        "kind_id",
        "type_id",
        "manufacturer_id",
    )
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_equipment_options(actor=actor, **filters)


class EquipmentCategoryOptionsAPIView(OptionsAPIView):
    """List category equipment as compact options, optionally filtering for assignable items (ADR 002)."""

    permission_classes = EQUIPMENT_PERMISSIONS
    schema_description = (
        "Large category Equipment selectors require q or at least one declared parent filter: kind_id, type_id, "
        "or manufacturer_id. include_ids, lifecycle_status, assigned, and assignable do not satisfy this requirement."
    )
    model = None
    queryset_provider = None
    entity_name = None
    required_attributes = ("model", "queryset_provider")
    category_fields = ()

    query_serializer = CategoryOptionsQuerySerializer
    size_class = SizeClass.LARGE
    required_any = ("q", "kind_id", "type_id", "manufacturer_id")
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return category_options_queryset(self.model, self.category_fields, actor=actor, **filters)


# 1. Equipment Categories
class EquipmentCategoriesListAPIView(AppListAPIView, EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("EquipmentCategoriesCatalogList", EquipmentCategorySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self.list_response_sync(list_equipment_categories())


class EquipmentCategoriesDetailAPIView(EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentCategoriesCatalogDetail", EquipmentCategorySerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, category_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_equipment_category(category_id=category_id))


class EquipmentCategoriesOptionsAPIView(OptionsAPIView):
    permission_classes = EQUIPMENT_PERMISSIONS
    query_serializer = OptionsQueryMixin
    size_class = SizeClass.SMALL
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_equipment_category_options(actor=actor, **filters)


# 2. Equipment Kinds
class EquipmentKindListAPIView(AppListAPIView, EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        query=EquipmentKindOptionsQuerySerializer,
        success=ResponseContract.paginated("EquipmentKindCatalogList", EquipmentKindSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        return self.list_response_sync(list_equipment_kinds(category_id=query.get("category_id") if query else None))


class EquipmentKindDetailAPIView(EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentKindCatalogDetail", EquipmentKindSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, kind_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_equipment_kind(kind_id=kind_id))


class EquipmentKindOptionsAPIView(OptionsAPIView):
    permission_classes = EQUIPMENT_PERMISSIONS
    query_serializer = EquipmentKindOptionsQuerySerializer
    size_class = SizeClass.SMALL
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_equipment_kind_options(actor=actor, **filters)


# 3. Equipment Types
class EquipmentTypeListAPIView(AppListAPIView, EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        query=EquipmentTypeOptionsQuerySerializer,
        success=ResponseContract.paginated("EquipmentTypeCatalogList", EquipmentTypeSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        kind_id = query.get("kind_id") if query else None
        category_id = query.get("category_id") if query else None
        return self.list_response_sync(list_equipment_types(kind_id=kind_id, category_id=category_id))


class EquipmentTypeDetailAPIView(EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentTypeCatalogDetail", EquipmentTypeSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, type_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_equipment_type(type_id=type_id))


class EquipmentTypeOptionsAPIView(OptionsAPIView):
    permission_classes = EQUIPMENT_PERMISSIONS
    query_serializer = EquipmentTypeOptionsQuerySerializer
    size_class = SizeClass.LARGE
    required_any = ("q", "kind_id", "category_id")
    schema_description = "Large Equipment type selectors require q, kind_id, or category_id."
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_equipment_type_options(actor=actor, **filters)


# 4. Equipment Manufacturers
class EquipmentManufacturerListAPIView(AppListAPIView, EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        query=EquipmentManufacturerOptionsQuerySerializer,
        success=ResponseContract.paginated("EquipmentManufacturerCatalogList", EquipmentManufacturerSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        return self.list_response_sync(
            list_equipment_manufacturers(category_id=query.get("category_id") if query else None)
        )


class EquipmentManufacturerDetailAPIView(EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentManufacturerCatalogDetail", EquipmentManufacturerSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, manufacturer_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_equipment_manufacturer(manufacturer_id=manufacturer_id))


class EquipmentManufacturerOptionsAPIView(OptionsAPIView):
    permission_classes = EQUIPMENT_PERMISSIONS
    query_serializer = EquipmentManufacturerOptionsQuerySerializer
    size_class = SizeClass.LARGE
    required_any = ("q", "category_id")
    schema_description = "Large Equipment manufacturer selectors require q or category_id."
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_equipment_manufacturer_options(actor=actor, **filters)


# 5. Equipment Product Models
class EquipmentProductModelListAPIView(AppListAPIView, EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        query=EquipmentProductModelOptionsQuerySerializer,
        success=ResponseContract.paginated("EquipmentProductModelCatalogList", EquipmentProductModelSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        manufacturer_id = query.get("manufacturer_id") if query else None
        type_id = query.get("type_id") if query else None
        return self.list_response_sync(list_equipment_product_models(manufacturer_id=manufacturer_id, type_id=type_id))


class EquipmentProductModelDetailAPIView(EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentProductModelCatalogDetail", EquipmentProductModelSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, model_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_equipment_product_model(model_id=model_id))


class EquipmentProductModelOptionsAPIView(OptionsAPIView):
    permission_classes = EQUIPMENT_PERMISSIONS
    query_serializer = EquipmentProductModelOptionsQuerySerializer
    size_class = SizeClass.LARGE
    required_any = ("q", "manufacturer_id", "type_id")
    schema_description = "Large Equipment product-model selectors require q, manufacturer_id, or type_id."
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_equipment_product_model_options(actor=actor, **filters)


# 6. Departments
class DepartmentListAPIView(AppListAPIView, EquipmentAPIView):
    permission_classes = ORGANIZATION_PERMISSIONS
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("DepartmentCatalogList", DepartmentSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self.list_response_sync(list_departments())


class DepartmentDetailAPIView(EquipmentAPIView):
    permission_classes = ORGANIZATION_PERMISSIONS
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        success=ResponseContract.success("DepartmentCatalogDetail", DepartmentSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, department_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_department(department_id=department_id))


class DepartmentOptionsAPIView(OptionsAPIView):
    query_serializer = OptionsQueryMixin
    size_class = SizeClass.SMALL
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_department_options(actor=actor, **filters)


# 7. Resource Groups
class ResourceGroupListAPIView(AppListAPIView, EquipmentAPIView):
    permission_classes = ORGANIZATION_PERMISSIONS
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        query=ResourceGroupOptionsQuerySerializer,
        success=ResponseContract.paginated("ResourceGroupCatalogList", ResourceGroupCatalogSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        department_id = query.get("department_id") if query else None
        return self.list_response_sync(list_resource_groups(department_id=department_id))


class ResourceGroupDetailAPIView(EquipmentAPIView):
    permission_classes = ORGANIZATION_PERMISSIONS
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        success=ResponseContract.success("ResourceGroupCatalogDetail", ResourceGroupCatalogSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, group_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_resource_group(group_id=group_id))


class ResourceGroupOptionsAPIView(OptionsAPIView):
    query_serializer = ResourceGroupOptionsQuerySerializer
    size_class = SizeClass.SMALL
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_resource_group_options(actor=actor, **filters)
