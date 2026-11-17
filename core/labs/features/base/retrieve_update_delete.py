"""Reusable retrieve, update, and delete API endpoint template."""

from typing import Any

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import extend_schema_view
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppDetailAPIView

from .common import FeatureAPIView


class RetrieveUpdateDeleteAPIView(AppDetailAPIView, FeatureAPIView):
    """Domain-neutral CRUD lifecycle for resources, bookings, monitoring, and other models."""

    model = None
    queryset_provider = None
    update_serializer_class = None
    response_serializer_class = None
    entity_name = None
    lock_on_write = False
    required_attributes = (
        "model",
        "queryset_provider",
        "update_serializer_class",
        "response_serializer_class",
        "entity_name",
    )

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        response_serializer = getattr(cls, "response_serializer_class", None)
        update_serializer = getattr(cls, "update_serializer_class", None)
        if response_serializer is None or update_serializer is None:
            return

        success = ResponseContract.success(f"{cls.__name__}Response", response_serializer)
        update_contract = OperationContract(
            request=update_serializer,
            success=success,
            bad_request=ResponseContract.problem(status.HTTP_400_BAD_REQUEST),
            validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
            not_found=ResponseContract.problem(status.HTTP_404_NOT_FOUND),
            conflict=ResponseContract.problem(status.HTTP_409_CONFLICT),
        )
        cls.get_contract = OperationContract(
            success=success,
            not_found=ResponseContract.problem(status.HTTP_404_NOT_FOUND),
        )
        cls.patch_contract = update_contract
        cls.put_contract = update_contract
        cls.delete_contract = OperationContract(
            success=ResponseContract.no_content(),
            not_found=ResponseContract.problem(status.HTTP_404_NOT_FOUND),
            conflict=ResponseContract.problem(status.HTTP_409_CONFLICT),
        )
        async_methods = [
            method for method in ("get", "patch", "put", "delete") if iscoroutinefunction(getattr(cls, method))
        ]
        extend_schema_view(
            get=cls.get_contract.schema(),
            patch=cls.patch_contract.schema(),
            put=cls.put_contract.schema(),
            delete=cls.delete_contract.schema(),
        )(cls)
        # Spectacular isolates inherited handlers with synchronous wrappers.
        for method in async_methods:
            markcoroutinefunction(getattr(cls, method))

    def get_queryset(self):
        return self.queryset_provider()

    def get_object_queryset(self):
        """Provide the write lookup; subclasses may use a leaner queryset."""
        return self.get_queryset()

    def get_write_queryset(self):
        queryset = self.get_object_queryset()
        return queryset.select_for_update() if self.lock_on_write else queryset

    def get_old_values(self, instance, serializer) -> dict[str, Any]:
        """Optional mutation-context hook; no auditing assumptions in the base."""
        return {}

    def get_response_instance(self, instance):
        """Optional response hydration hook; domain services may return computed data."""
        return instance

    def get_integrity_error_response(self, error):
        """Domain views may translate a specifically recognized constraint."""
        return None

    def get_save_kwargs(self, request: Request) -> dict:
        """Domain subclasses opt in to actor stamps or other model-specific fields."""
        return {}

    def validate_update(self, instance, serializer, pk: int):
        return None

    def perform_update(self, instance, serializer, request: Request):
        return serializer.save(**self.get_save_kwargs(request))

    def after_update(self, instance, serializer, request: Request, old_values: dict[str, Any]) -> None:
        pass

    def perform_delete(self, instance, request: Request) -> None:
        instance.delete()

    def before_delete(self, instance, request: Request) -> None:
        pass

    def handle_get(self, request: Request, pk: int, *args, **kwargs) -> Response:
        self.validate_configuration()
        instance = get_object_or_404(self.get_queryset(), pk=pk)
        return self.respond(instance)

    def _update_response(self, request: Request, pk: int) -> Response:
        self.validate_configuration()
        try:
            with transaction.atomic():
                instance = get_object_or_404(self.get_write_queryset(), pk=pk)
                serializer, error = self.validate_request(
                    instance=instance,
                    data=request.data,
                    partial=request.method.upper() == "PATCH",
                )
                if error is not None:
                    return error
                conflict = self.validate_update(instance, serializer, pk)
                if conflict:
                    code, errors = conflict
                    return self.respond_problem("conflict", errors=errors, code=code)
                old_values = self.get_old_values(instance, serializer)
                updated = self.perform_update(instance, serializer, request)
                updated = self.get_response_instance(updated)
                self.after_update(updated, serializer, request, old_values)
        except ValidationError as error:
            errors = error.message_dict if hasattr(error, "error_dict") else error.messages
            response_name = "validation_error"
            if self.operation().responses.validation_error is None:
                response_name = "bad_request"
            return self.respond_problem(response_name, errors=errors, code="validation_failed")
        except IntegrityError as error:
            response = self.get_integrity_error_response(error)
            if response is None:
                raise
            return response
        return self.respond(updated)

    def handle_patch(self, request: Request, pk: int, *args, **kwargs) -> Response:
        return self._update_response(request, pk)

    def handle_put(self, request: Request, pk: int, *args, **kwargs) -> Response:
        return self._update_response(request, pk)

    def handle_delete(self, request: Request, pk: int, *args, **kwargs) -> Response:
        self.validate_configuration()
        with transaction.atomic():
            instance = get_object_or_404(self.get_write_queryset(), pk=pk)
            self.before_delete(instance, request)
            self.perform_delete(instance, request)
        return Response(status=status.HTTP_204_NO_CONTENT)
