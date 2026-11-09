"""Reusable list and create API endpoint template."""

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.db import transaction
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import extend_schema_view
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.common.api.pagination import PageNumberQuerySerializer

from .common import FeatureAPIView


class ListCreateAPIView(AppListAPIView, FeatureAPIView):
    model = None
    queryset_provider = None
    list_serializer_class = None
    create_serializer_class = None
    entity_name = None
    required_attributes = (
        "model",
        "queryset_provider",
        "list_serializer_class",
        "create_serializer_class",
        "entity_name",
    )

    @classmethod
    def get_openapi_list_response(cls):
        return ResponseContract.paginated(f"{cls.__name__}List", cls.list_serializer_class).schema

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        list_serializer = getattr(cls, "list_serializer_class", None)
        create_serializer = getattr(cls, "create_serializer_class", None)
        if list_serializer is None or create_serializer is None:
            return
        cls.get_contract = OperationContract(
            query=PageNumberQuerySerializer,
            success=ResponseContract.paginated(f"{cls.__name__}List", list_serializer),
            bad_request=ResponseContract.problem(status.HTTP_400_BAD_REQUEST),
            validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        )
        cls.post_contract = OperationContract(
            request=create_serializer,
            success=ResponseContract.created(cls.__name__, list_serializer),
            bad_request=ResponseContract.problem(status.HTTP_400_BAD_REQUEST),
            validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        )
        async_methods = [method for method in ("get", "post") if iscoroutinefunction(getattr(cls, method))]
        extend_schema_view(get=cls.get_contract.schema(), post=cls.post_contract.schema())(cls)
        for method in async_methods:
            markcoroutinefunction(getattr(cls, method))

    def get_queryset(self, request: Request):
        return self.queryset_provider()

    def get_save_kwargs(self, request: Request) -> dict:
        """Subclasses opt in to domain-specific save fields or actor stamps."""
        return {}

    def validate_create(self, serializer):
        return None

    def perform_create(self, serializer, request: Request):
        return serializer.save(**self.get_save_kwargs(request))

    def after_create(self, instance, serializer, request: Request) -> None:
        pass

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        self.validate_configuration()
        _, error = self.validate_query()
        if error is not None:
            return error
        queryset = self.get_queryset(request)
        return self.list_response_sync(queryset)

    def handle_post(self, request: Request, *args, **kwargs) -> Response:
        self.validate_configuration()
        serializer, error = self.validate_request()
        if error is not None:
            return error
        conflict = self.validate_create(serializer)
        if conflict:
            code, errors = conflict
            return self.respond_problem("conflict", errors=errors, code=code)
        with transaction.atomic():
            instance = self.perform_create(serializer, request)
            self.after_create(instance, serializer, request)
        return self.respond(instance)
