from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.common.api.pagination import PageNumberQuerySerializer
from core.common.api.permissions import HasAPIKeyAccess
from core.labs.features.base import CommandAPIView
from core.labs.features.expense import public
from core.labs.features.expense.api.serializers import (
    ExpensePaymentSerializer,
    ExpenseSerializer,
    FinancialReportQuerySerializer,
    FinancialReportResponseSerializer,
)
from core.labs.features.expense.public import (
    CreateExpenseInput,
    CreateExpensePaymentInput,
)
from core.users.public import IsLabCoordinatorReadWrite


class ExpenseAPIView(AppListAPIView, CommandAPIView):
    # Reads and writes: lab coordinators and admins (owner decision 2026-11-11), and API keys.
    permission_classes = [HasAPIKeyAccess | IsLabCoordinatorReadWrite]


class RoomExpenseListCreateAPIView(ExpenseAPIView):
    """List and create expense obligations for a room."""

    schema_tags = ("Expenses",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("RoomExpenseList", ExpenseSerializer),
        not_found=ResponseContract.not_found(),
    )
    post_contract = OperationContract(
        request=ExpenseSerializer,
        success=ResponseContract.created("RoomExpense", ExpenseSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(422),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, room_id: int, *args, **kwargs) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: public.list_room_expenses(room_id=room_id))

    def handle_post(self, request: Request, room_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request(serializer_class=ExpenseSerializer)
        if error is not None:
            return error
        command = CreateExpenseInput(room_id=room_id, **serializer.validated_data)
        return self._execute(lambda: public.create_expense(command, actor=self.acting_user))


class ExpensePaymentListCreateAPIView(ExpenseAPIView):
    """List and record payments or refunds against an expense."""

    schema_tags = ("Expenses",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("ExpensePaymentList", ExpensePaymentSerializer),
        not_found=ResponseContract.not_found(),
    )
    post_contract = OperationContract(
        request=ExpensePaymentSerializer,
        success=ResponseContract.created("ExpensePayment", ExpensePaymentSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(422),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, expense_id: int, *args, **kwargs) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: public.list_expense_payments(expense_id=expense_id))

    def handle_post(self, request: Request, expense_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request(serializer_class=ExpensePaymentSerializer)
        if error is not None:
            return error
        command = CreateExpensePaymentInput(expense_id=expense_id, **serializer.validated_data)
        return self._execute(lambda: public.create_expense_payment(command, actor=self.acting_user))


class FinancialReportAPIView(ExpenseAPIView):
    """Aggregate financial report and expenditure metrics across lab facilities."""

    schema_tags = ("Expenses",)
    get_contract = OperationContract(
        query=FinancialReportQuerySerializer,
        success=ResponseContract.success("FinancialReport", FinancialReportResponseSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        query_data, error = self.validate_query()
        if error is not None:
            return error
        params = dict(query_data or {})
        return self._execute(lambda: public.get_financial_report(**params))


class RoomFinancialReportAPIView(ExpenseAPIView):
    """Aggregate financial report for a specific laboratory room."""

    schema_tags = ("Expenses",)
    get_contract = OperationContract(
        query=FinancialReportQuerySerializer,
        success=ResponseContract.success("RoomFinancialReport", FinancialReportResponseSerializer),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, room_id: int, *args, **kwargs) -> Response:
        query_data, error = self.validate_query()
        if error is not None:
            return error
        params = dict(query_data or {})
        params["room_id"] = room_id
        return self._execute(lambda: public.get_financial_report(**params))


@extend_schema_view(
    get=extend_schema(
        deprecated=True,
        description="Deprecated alias for financial report. Use /api/labs/expenses/report instead.",
    ),
)
class DeprecatedFinancialReportAPIView(FinancialReportAPIView):
    """Deprecated alias for financial report.

    Use /api/labs/expenses/report instead.
    """

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Deprecation"] = "true"
        response["Sunset"] = "Wed, 01 Jul 2027 00:00:00 GMT"
        response["Link"] = '</api/labs/expenses/report>; rel="successor-version"'
        return response


__all__ = [
    "DeprecatedFinancialReportAPIView",
    "ExpensePaymentListCreateAPIView",
    "FinancialReportAPIView",
    "RoomExpenseListCreateAPIView",
    "RoomFinancialReportAPIView",
]
