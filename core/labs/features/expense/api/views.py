from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.common.api.pagination import PageNumberQuerySerializer
from core.labs.features.base import CommandAPIView
from core.labs.features.base.access import FINANCE_ACCESS
from core.labs.features.expense import public
from core.labs.features.expense.api.serializers import (
    ExpenseCreateSerializer,
    ExpenseListQuerySerializer,
    ExpensePaymentSerializer,
    ExpensePaymentWriteSerializer,
    ExpenseSerializer,
    ExpenseWriteSerializer,
    FinancialReportQuerySerializer,
    FinancialReportResponseSerializer,
    RoomExpenseListQuerySerializer,
)
from core.labs.features.expense.public import (
    CreateExpenseInput,
    CreateExpensePaymentInput,
)


class ExpenseAPIView(AppListAPIView, CommandAPIView):
    # Reads and writes: lab coordinators and admins (owner decision 2026-11-11), and API keys.
    permission_classes = FINANCE_ACCESS


class ExpenseListCreateAPIView(ExpenseAPIView):
    """List and create expense obligations for any supported lab resource (room, station, bench, equipment, license)."""

    schema_tags = ("Expenses",)
    get_contract = OperationContract(
        query=ExpenseListQuerySerializer,
        success=ResponseContract.paginated("ExpenseList", ExpenseSerializer),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
    )
    post_contract = OperationContract(
        request=ExpenseCreateSerializer,
        success=ResponseContract.created("Expense", ExpenseSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(422),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        query_data, error = self.validate_query()
        if error is not None:
            return error
        params = dict(query_data or {})
        return self._execute(
            lambda: public.list_expenses(
                resource_kind=params.get("resource_kind"),
                resource_id=params.get("resource_id"),
                expense_type=params.get("expense_type"),
                billing_period=params.get("billing_period"),
            )
        )

    def handle_post(self, request: Request, *args, **kwargs) -> Response:
        serializer, error = self.validate_request(serializer_class=ExpenseCreateSerializer)
        if error is not None:
            return error
        command = CreateExpenseInput(**serializer.validated_data)
        return self._execute(lambda: public.create_expense(command, actor=self.acting_user))


class RoomExpenseListCreateAPIView(ExpenseAPIView):
    """List and create expense obligations for a room."""

    schema_tags = ("Expenses",)
    get_contract = OperationContract(
        query=RoomExpenseListQuerySerializer,
        success=ResponseContract.paginated("RoomExpenseList", ExpenseSerializer),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
    )
    post_contract = OperationContract(
        request=ExpenseWriteSerializer,
        success=ResponseContract.created("RoomExpense", ExpenseSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(422),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, room_id: int, *args, **kwargs) -> Response:
        query_data, error = self.validate_query()
        if error is not None:
            return error
        params = dict(query_data or {})
        return self._execute(
            lambda: public.list_room_expenses(
                room_id=room_id,
                expense_type=params.get("expense_type"),
                billing_period=params.get("billing_period"),
            )
        )

    def handle_post(self, request: Request, room_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request(serializer_class=ExpenseWriteSerializer)
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
        request=ExpensePaymentWriteSerializer,
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
        serializer, error = self.validate_request(serializer_class=ExpensePaymentWriteSerializer)
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
        not_found=ResponseContract.not_found(),
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


__all__ = [
    "ExpenseListCreateAPIView",
    "ExpensePaymentListCreateAPIView",
    "FinancialReportAPIView",
    "RoomExpenseListCreateAPIView",
    "RoomFinancialReportAPIView",
]
