"""HTTP views for the resource audit feature by ID, SKU, and UID."""

import uuid
from typing import Any

from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.common.api.pagination import PageNumberQuerySerializer
from core.labs.features.base import CommandAPIView
from core.labs.features.resource_audit import public
from core.labs.features.resource_audit.api.serializers import (
    RecordResourceAuditRequestSerializer,
    ResourceAuditItemSerializer,
    ResourceAuditListQuerySerializer,
    UpdateResourceAuditRequestSerializer,
)


class ResourceAuditAPIView(AppListAPIView, CommandAPIView):
    """Base API view for resource auditing."""

    schema_tags = ("Resource Audit",)


class ResourceAuditByIdView(ResourceAuditAPIView):
    """List or record audits for a resource identified by integer ID."""

    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("ResourceAuditListById", ResourceAuditItemSerializer),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
    )
    post_contract = OperationContract(
        request=RecordResourceAuditRequestSerializer,
        success=ResponseContract.created("ResourceAuditItemById", ResourceAuditItemSerializer),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
        validation_error=ResponseContract.problem(422),
    )

    def handle_get(self, request: Request, resource_id: int, *args: Any, **kwargs: Any) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: public.list_audits_by_id(resource_id))

    def handle_post(self, request: Request, resource_id: int, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request(serializer_class=RecordResourceAuditRequestSerializer)
        if error is not None:
            return error
        data = serializer.validated_data
        cmd = public.RecordAuditByIdInput(
            resource_id=resource_id,
            result=data["result"],
            remarks=data.get("remarks", ""),
            audited_at=data.get("audited_at"),
        )
        return self._execute(lambda: public.record_audit_by_id(cmd, actor=self.acting_user))


class ResourceAuditBySkuView(ResourceAuditAPIView):
    """List or record audits for a resource identified by business SKU."""

    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("ResourceAuditListBySku", ResourceAuditItemSerializer),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
    )
    post_contract = OperationContract(
        request=RecordResourceAuditRequestSerializer,
        success=ResponseContract.created("ResourceAuditItemBySku", ResourceAuditItemSerializer),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
        validation_error=ResponseContract.problem(422),
    )

    def handle_get(self, request: Request, sku: str, *args: Any, **kwargs: Any) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: public.list_audits_by_sku(sku))

    def handle_post(self, request: Request, sku: str, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request(serializer_class=RecordResourceAuditRequestSerializer)
        if error is not None:
            return error
        data = serializer.validated_data
        cmd = public.RecordAuditBySkuInput(
            sku=sku,
            result=data["result"],
            remarks=data.get("remarks", ""),
            audited_at=data.get("audited_at"),
        )
        return self._execute(lambda: public.record_audit_by_sku(cmd, actor=self.acting_user))


class ResourceAuditByUidView(ResourceAuditAPIView):
    """List or record audits for a resource identified by system UUID."""

    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("ResourceAuditListByUid", ResourceAuditItemSerializer),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
    )
    post_contract = OperationContract(
        request=RecordResourceAuditRequestSerializer,
        success=ResponseContract.created("ResourceAuditItemByUid", ResourceAuditItemSerializer),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
        validation_error=ResponseContract.problem(422),
    )

    def handle_get(self, request: Request, uid: uuid.UUID, *args: Any, **kwargs: Any) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: public.list_audits_by_uid(uid))

    def handle_post(self, request: Request, uid: uuid.UUID, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request(serializer_class=RecordResourceAuditRequestSerializer)
        if error is not None:
            return error
        data = serializer.validated_data
        cmd = public.RecordAuditByUidInput(
            uid=uid,
            result=data["result"],
            remarks=data.get("remarks", ""),
            audited_at=data.get("audited_at"),
        )
        return self._execute(lambda: public.record_audit_by_uid(cmd, actor=self.acting_user))


class TypedResourceAuditListCreateView(ResourceAuditAPIView):
    """List or record audits for a typed resource."""

    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("TypedResourceAuditList", ResourceAuditItemSerializer),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
    )
    post_contract = OperationContract(
        request=RecordResourceAuditRequestSerializer,
        success=ResponseContract.created("TypedResourceAuditItem", ResourceAuditItemSerializer),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
        validation_error=ResponseContract.problem(422),
    )

    def handle_get(self, request: Request, resource_type: str, resource_id: str, *args: Any, **kwargs: Any) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: public.list_audits_for_resource(resource_id, resource_type=resource_type))

    def handle_post(self, request: Request, resource_type: str, resource_id: str, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request(serializer_class=RecordResourceAuditRequestSerializer)
        if error is not None:
            return error
        data = serializer.validated_data
        cmd = public.RecordResourceAuditInput(
            identifier=resource_id,
            identifier_type="id" if resource_id.isdigit() else "sku",
            resource_type=resource_type,
            result=data["result"],
            remarks=data.get("remarks", ""),
            audited_at=data.get("audited_at"),
        )
        return self._execute(lambda: public.record_resource_audit(cmd, actor=self.acting_user))


class AllResourceAuditListAPIView(ResourceAuditAPIView):
    """Query and filter audits across all lab resources."""

    get_contract = OperationContract(
        query=ResourceAuditListQuerySerializer,
        success=ResponseContract.paginated("AllResourceAuditList", ResourceAuditItemSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        clean_filters = {
            k: v
            for k, v in (filters or {}).items()
            if k not in ("page", "page_size")
        }
        return self._execute(lambda: public.list_all_resource_audits(**clean_filters))


class ResourceAuditDetailAPIView(ResourceAuditAPIView):
    """Retrieve, update, or delete a single audit entry."""

    get_contract = OperationContract(
        success=ResponseContract.success("ResourceAuditDetail", ResourceAuditItemSerializer),
        not_found=ResponseContract.not_found(),
    )
    patch_contract = OperationContract(
        request=UpdateResourceAuditRequestSerializer,
        success=ResponseContract.success("ResourceAuditDetail", ResourceAuditItemSerializer),
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
        validation_error=ResponseContract.problem(422),
    )
    delete_contract = OperationContract(
        success=ResponseContract.no_content(),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, audit_id: int, *args: Any, **kwargs: Any) -> Response:
        def _get():
            audit = public.get_resource_audit(audit_id)
            if not audit:
                raise public.ResourceAuditNotFoundError(f"Audit {audit_id} not found.")
            return audit

        return self._execute(_get)

    def handle_patch(self, request: Request, audit_id: int, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request(serializer_class=UpdateResourceAuditRequestSerializer)
        if error is not None:
            return error
        data = serializer.validated_data
        cmd = public.UpdateResourceAuditInput(
            audit_id=audit_id,
            result=data.get("result"),
            remarks=data.get("remarks"),
            audited_at=data.get("audited_at"),
        )
        return self._execute(lambda: public.update_resource_audit(cmd, actor=self.acting_user))

    def handle_delete(self, request: Request, audit_id: int, *args: Any, **kwargs: Any) -> Response:
        return self._execute(
            lambda: public.delete_resource_audit(audit_id, actor=self.acting_user),
            delete=True,
        )
