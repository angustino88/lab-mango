from drf_api_contracts import OperationContract, ResponseContract
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_api_key.permissions import HasAPIKey

from core.common.api.api_views import AppListAPIView
from core.common.api.correlation import get_request_id
from core.common.api.command_views import FeatureAPIView
from core.common.api.pagination import PageNumberQuerySerializer
from core.labs.features.base import CommandAPIView
from core.labs.features.procurement import public
from core.labs.features.procurement.api.serializers import (
    DraftLineInputSerializer,
    DraftLinePatchInputSerializer,
    PurchaseDetailSerializer,
    PurchaseDraftHeaderInputSerializer,
    PurchaseDraftHeaderOutputSerializer,
    PurchaseItemReadSerializer,
    PurchaseItemDetailSerializer,
    PurchaseItemResourceCreateSerializer,
    PurchaseItemResourceSerializer,
    PurchaseItemSerializer,
    PurchasePriorityOptionSerializer,
    PurchasePriorityQuerySerializer,
    PurchaseSerializer,
    PurchaseTransactionSerializer,
)
from core.labs.features.procurement.public import (
    CreateDraftLineInput,
    CreatePurchaseInput,
    CreatePurchaseItemInput,
    CreatePurchaseItemResourceInput,
    CreatePurchaseTransactionInput,
    PurchaseLineInput,
    DeleteDraftLineInput,
    DraftLineInput,
    UpdateDraftLineInput,
    UpdatePurchaseDraftInput,
)
from core.labs.features.procurement.exceptions import PurchaseETagRequired, PurchaseMachineWriteForbidden
from core.users.public import IsLabCoordinatorReadWrite


class ProcurementAPIView(AppListAPIView, CommandAPIView):
    # Reads and writes: lab coordinators and admins (owner decision 2026-11-11), and API keys.
    permission_classes = [HasAPIKey | IsLabCoordinatorReadWrite]


class PurchasePriorityOptionsAPIView(FeatureAPIView):
    schema_tags = ("Procurement",)
    permission_classes = [HasAPIKey | IsLabCoordinatorReadWrite]
    get_contract = OperationContract(
        query=PurchasePriorityQuerySerializer,
        success=ResponseContract.success("PurchasePriorityOptions", PurchasePriorityOptionSerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request, *args, **kwargs):
        query = PurchasePriorityQuerySerializer(data=request.query_params, context={"request": request})
        if not query.is_valid():
            return self.respond_problem("bad_request", code="invalid_query", errors=query.errors)
        serializer = query
        if error is not None:
            return error
        include_inactive = serializer.validated_data.get("include_inactive") == "true"
        return self.respond(PurchasePriorityOptionSerializer(
            public.list_purchase_priorities(include_inactive=include_inactive), many=True
        ).data)


class PurchaseDetailAPIView(ProcurementAPIView):
    schema_tags = ("Procurement",)
    get_contract = OperationContract(
        success=ResponseContract.success("PurchaseDetail", PurchaseDetailSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request, purchase_id: int, *args, **kwargs):
        return self._execute(
            lambda: public.get_purchase(purchase_id=purchase_id),
            project=lambda purchase: self._detail_response(purchase),
        )

    def _detail_response(self, purchase):
        response = self.respond(PurchaseDetailSerializer(purchase).data)
        response["ETag"] = public.purchase_etag(purchase)
        return response


class PurchaseDraftHeaderAPIView(ProcurementAPIView):
    schema_tags = ("Procurement",)
    patch_contract = OperationContract(
        request=PurchaseDraftHeaderInputSerializer,
        success=ResponseContract.success("PurchaseDraftHeader", PurchaseDraftHeaderOutputSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(422),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
    )

    def handle_patch(self, request, purchase_id: int, *args, **kwargs):
        self._require_user_write()
        if "If-Match" not in request.headers:
            raise PurchaseETagRequired("If-Match is required for this operation.")
        serializer, error = self.validate_request(serializer_class=PurchaseDraftHeaderInputSerializer, partial=True)
        if error is not None:
            return error
        result = self._execute(
            lambda: public.update_purchase_draft(
                UpdatePurchaseDraftInput(
                    purchase_id=purchase_id,
                    if_match=request.headers.get("If-Match"),
                    changes=serializer.validated_data,
                    request_id=get_request_id(request),
                ),
                actor=self.acting_user,
            ),
            project=lambda purchase: self._draft_response(purchase),
        )
        return result

    def _draft_response(self, purchase):
        response = self.respond(PurchaseDraftHeaderOutputSerializer(purchase).data)
        response["ETag"] = public.purchase_etag(purchase)
        return response

    def _require_user_write(self):
        if self.acting_user is None:
            raise PurchaseMachineWriteForbidden("API-key writes are not enabled for purchase drafts.")


class PurchaseDraftLineListCreateAPIView(ProcurementAPIView):
    pagination_class = None
    schema_tags = ("Procurement",)
    get_contract = OperationContract(
        success=ResponseContract.success("PurchaseDraftLineList", PurchaseItemDetailSerializer, many=True),
        not_found=ResponseContract.not_found(),
    )
    post_contract = OperationContract(
        request=DraftLineInputSerializer,
        success=ResponseContract.created("PurchaseDraftLine", PurchaseItemDetailSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(422),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
    )

    def handle_get(self, request, purchase_id: int, *args, **kwargs):
        return self._execute(
            lambda: list(public.list_purchase_items(purchase_id=purchase_id)[:500]),
            project=lambda rows: PurchaseItemDetailSerializer(rows, many=True).data,
        )

    def handle_post(self, request, purchase_id: int, *args, **kwargs):
        self._require_user_write()
        serializer, error = self.validate_request(serializer_class=DraftLineInputSerializer)
        if error is not None:
            return error
        command = CreateDraftLineInput(
            purchase_id=purchase_id,
            if_match=None,
            line=DraftLineInput(**serializer.validated_data),
            request_id=get_request_id(request),
        )
        return self._execute(
            lambda: public.create_draft_line(command, actor=self.acting_user),
            project=lambda item: self._item_response(item),
        )

    def _require_user_write(self):
        if self.acting_user is None:
            raise PurchaseMachineWriteForbidden("API-key writes are not enabled for purchase drafts.")

    def _item_response(self, item):
        from rest_framework.response import Response

        response = Response(PurchaseItemDetailSerializer(item).data, status=status.HTTP_201_CREATED)
        response["ETag"] = public.item_etag(item)
        response["Location"] = f"/api/purchase-items/{item.pk}"
        return response


class PurchaseDraftLineDetailAPIView(ProcurementAPIView):
    schema_tags = ("Procurement",)
    get_contract = OperationContract(
        success=ResponseContract.success("PurchaseDraftLine", PurchaseItemDetailSerializer),
        not_found=ResponseContract.not_found(),
    )
    patch_contract = OperationContract(
        request=DraftLinePatchInputSerializer,
        success=ResponseContract.success("PurchaseDraftLine", PurchaseItemDetailSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(422),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
    )
    delete_contract = OperationContract(
        success=ResponseContract.empty("PurchaseDraftLineDeleted", status_code=204),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
    )

    def handle_get(self, request, purchase_id: int, item_id: int, *args, **kwargs):
        return self._execute(
            lambda: public.get_purchase_item(purchase_id=purchase_id, item_id=item_id),
            project=lambda item: self._detail_response(item),
        )

    def handle_patch(self, request, purchase_id: int, item_id: int, *args, **kwargs):
        self._require_user_write()
        if "If-Match" not in request.headers:
            raise PurchaseETagRequired("If-Match is required for this operation.")
        serializer, error = self.validate_request(serializer_class=DraftLinePatchInputSerializer, partial=True)
        if error is not None:
            return error
        return self._execute(
            lambda: public.update_draft_line(
                UpdateDraftLineInput(
                    purchase_id=purchase_id,
                    item_id=item_id,
                    if_match=request.headers.get("If-Match"),
                    changes=serializer.validated_data,
                    request_id=get_request_id(request),
                ),
                actor=self.acting_user,
            ),
            project=lambda item: self._detail_response(item),
        )

    def handle_delete(self, request, purchase_id: int, item_id: int, *args, **kwargs):
        self._require_user_write()
        if "If-Match" not in request.headers:
            raise PurchaseETagRequired("If-Match is required for this operation.")
        response = self._execute(
            lambda: public.delete_draft_line(
                DeleteDraftLineInput(
                    purchase_id=purchase_id,
                    item_id=item_id,
                    if_match=request.headers.get("If-Match"),
                    request_id=get_request_id(request),
                ),
                actor=self.acting_user,
            ),
            delete=True,
        )
        return response

    def _require_user_write(self):
        if self.acting_user is None:
            raise PurchaseMachineWriteForbidden("API-key writes are not enabled for purchase drafts.")

    def _detail_response(self, item):
        from rest_framework.response import Response

        response = Response(PurchaseItemDetailSerializer(item).data)
        response["ETag"] = public.item_etag(item)
        return response


class PurchaseListCreateAPIView(ProcurementAPIView):
    """List and create procurement purchase orders."""

    schema_tags = ("Procurement",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("PurchaseList", PurchaseSerializer),
    )
    post_contract = OperationContract(
        request=PurchaseSerializer,
        success=ResponseContract.created("Purchase", PurchaseSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(422),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(public.list_purchases)

    def handle_post(self, request: Request, *args, **kwargs) -> Response:
        serializer, error = self.validate_request(serializer_class=PurchaseSerializer)
        if error is not None:
            return error
        values = serializer.validated_data
        command = CreatePurchaseInput(
            **{key: value for key, value in values.items() if key != "items"},
            items=tuple(PurchaseLineInput(**item) for item in values.get("items", ())),
        )
        return self._execute(lambda: public.create_purchase(command, actor=self.acting_user))


class PurchaseItemListCreateAPIView(ProcurementAPIView):
    """List and create allocated purchase cost lines."""

    schema_tags = ("Procurement",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("PurchaseItemList", PurchaseItemReadSerializer),
    )
    post_contract = OperationContract(
        request=PurchaseItemSerializer,
        success=ResponseContract.created("PurchaseItem", PurchaseItemReadSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(422),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, purchase_id: int, *args, **kwargs) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: public.list_purchase_items(purchase_id=purchase_id))

    def handle_post(self, request: Request, purchase_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request(serializer_class=PurchaseItemSerializer)
        if error is not None:
            return error
        command = CreatePurchaseItemInput(purchase_id=purchase_id, **serializer.validated_data)
        return self._execute(lambda: public.create_purchase_item(command, actor=self.acting_user))


class PurchaseItemResourceListCreateAPIView(ProcurementAPIView):
    """List and allocate physical resources to a purchase line."""

    schema_tags = ("Procurement",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated(
            "PurchaseItemResourceList",
            PurchaseItemResourceSerializer,
        ),
    )
    post_contract = OperationContract(
        request=PurchaseItemResourceCreateSerializer,
        success=ResponseContract.created("PurchaseItemResource", PurchaseItemResourceSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(422),
        not_found=ResponseContract.not_found(),
    )

    def handle_post(self, request: Request, purchase_item_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request(serializer_class=PurchaseItemResourceCreateSerializer)
        if error is not None:
            return error

        values = serializer.validated_data
        command = CreatePurchaseItemResourceInput(
            purchase_item_id=purchase_item_id,
            resource_type_id=values["resource_type_id"],
            resource_id=values["resource_id"],
            acquisition_price=values["acquisition_price"],
        )
        return self._execute(lambda: public.create_purchase_item_resource(command, actor=self.acting_user))

    def handle_get(self, request: Request, purchase_item_id: int, *args, **kwargs) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: public.list_purchase_item_resources(purchase_item_id=purchase_item_id))


class PurchaseTransactionListCreateAPIView(ProcurementAPIView):
    """List and create purchase payments or refunds."""

    schema_tags = ("Procurement",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("PurchaseTransactionList", PurchaseTransactionSerializer),
    )
    post_contract = OperationContract(
        request=PurchaseTransactionSerializer,
        success=ResponseContract.created("PurchaseTransaction", PurchaseTransactionSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(422),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, purchase_id: int, *args, **kwargs) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: public.list_purchase_transactions(purchase_id=purchase_id))

    def handle_post(self, request: Request, purchase_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request(serializer_class=PurchaseTransactionSerializer)
        if error is not None:
            return error
        command = CreatePurchaseTransactionInput(
            purchase_id=purchase_id,
            **serializer.validated_data,
        )
        return self._execute(lambda: public.create_purchase_transaction(command, actor=self.acting_user))
