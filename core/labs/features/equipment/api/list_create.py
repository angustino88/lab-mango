"""Reusable HTTP list/create adapter for equipment models."""

from typing import Any, ClassVar, cast

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import extend_schema_view
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.common.api.pagination import ResultsSetPagination, with_page_query
from core.labs.features.base.resource_change_log import ResourceChangeLogMixin
from core.labs.features.equipment.application import CreateEquipmentInput, create_equipment
from core.labs.features.equipment.exceptions import SkuAlreadyExists

from .common import EquipmentAPIView, is_active_sku_unique_error, sku_exists
from .resource_filters import equipment_filter_spec


class EquipmentListCreateAPIView(ResourceChangeLogMixin, AppListAPIView, EquipmentAPIView):
    """Template for searchable equipment lists and audited creation."""

    model = None
    queryset_provider = None
    list_serializer_class = None
    create_response_serializer_class = None
    create_serializer_class = None
    entity_name = None

    text_search_fields: ClassVar[list[str]] = []
    list_filters: ClassVar[tuple] = ()
    distinct_search: ClassVar[bool] = False
    array_search_fields: ClassVar[dict] = {}
    status_filter_fk_field = None
    pagination_class = ResultsSetPagination

    class ListQuerySerializer(serializers.Serializer):
        search = serializers.CharField(required=False, allow_blank=True)
        page = serializers.IntegerField(required=False, min_value=1)
        page_size = serializers.IntegerField(required=False, min_value=1, max_value=100)

    @classmethod
    def get_openapi_list_response(cls):
        return ResponseContract.paginated(f"{cls.__name__}List", cls.list_serializer_class).schema

    required_attributes = (
        "model",
        "queryset_provider",
        "list_serializer_class",
        "create_serializer_class",
        "entity_name",
    )

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        list_serializer = getattr(cls, "list_serializer_class", None)
        create_serializer = getattr(cls, "create_serializer_class", None)
        if list_serializer is None or create_serializer is None:
            return
        list_contract = ResponseContract.paginated(cls.__name__, list_serializer)
        cls.filter_spec = equipment_filter_spec(
            cls.text_search_fields,
            cls.list_filters,
            distinct_search=cls.distinct_search,
        )
        cls.ListQuerySerializer = cast(
            Any, with_page_query(cls.filter_spec.serializer(f"{cls.__name__}ListQuerySerializer"))
        )
        cls.get_contract = OperationContract(
            query=cls.ListQuerySerializer,
            success=list_contract,
            bad_request=ResponseContract.bad_request(),
        )
        cls.post_contract = OperationContract(
            request=create_serializer,
            success=ResponseContract.created(
                cls.__name__,
                getattr(cls, "create_response_serializer_class", None) or list_serializer,
            ),
            bad_request=ResponseContract.bad_request(),
            validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
            conflict=ResponseContract.conflict(),
        )
        async_methods = [method for method in ("get", "post") if iscoroutinefunction(getattr(cls, method))]
        extend_schema_view(get=cls.get_contract.schema(), post=cls.post_contract.schema())(cls)
        for method in async_methods:
            markcoroutinefunction(getattr(cls, method))

    def get_queryset(self, request: Request):
        return self.queryset_provider()

    def prepare_list_results(self, instances):
        """Prepare list instances after filtering and pagination, before serialization."""
        return instances

    def get_save_kwargs(self, request: Request) -> dict:
        user = request.user if getattr(request.user, "is_authenticated", False) else None
        return {"creator": user, "last_modified_by": user} if user else {}

    def validate_create(self, serializer) -> None:
        sku = serializer.validated_data.get("sku")
        if sku and sku_exists(sku):
            raise SkuAlreadyExists

    def perform_create(self, serializer, request: Request):
        actor = request.user if getattr(request.user, "is_authenticated", False) else None
        return create_equipment(
            CreateEquipmentInput(fields=tuple(serializer.validated_data.items())),
            actor=actor,
        )

    def after_create(self, instance, serializer, request: Request) -> None:
        super().after_create(instance, serializer, request)
        if request.user.is_authenticated and hasattr(instance, "record_audit"):
            instance.record_audit(
                auditor=request.user,
                result="NOT_ASSESSED",
                remarks=f"{self.entity_name} created",
            )

    def handle_get(self, request, *args, **kwargs):
        self.validate_configuration()
        filters, error = self.validate_query()
        if error is not None:
            return error
        queryset = self.filter_spec.apply(self.get_queryset(request), filters)
        prepared = self.prepare_list_results(queryset)
        return self.list_response_sync(prepared)

    def handle_post(self, request: Request, *args, **kwargs) -> Response:
        self.validate_configuration()
        serializer, error = self.validate_request(data=request.data)
        if error is not None:
            return error

        self.validate_create(serializer)

        try:
            with transaction.atomic():
                instance = self.perform_create(serializer, request)
                self.after_create(instance, serializer, request)
                instance = get_object_or_404(self.queryset_provider(), pk=instance.pk)
        except ValidationError as error:
            errors = error.message_dict if hasattr(error, "error_dict") else error.messages
            return self.respond_problem("validation_error", errors=errors, code="validation_failed")
        except IntegrityError as error:
            if not is_active_sku_unique_error(error):
                raise
            raise SkuAlreadyExists from error
        return self.respond(instance)
