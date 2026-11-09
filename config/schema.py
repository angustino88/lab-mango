import re

from drf_api_contracts import ResponseSchemaFactory
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework.generics import GenericAPIView
from rest_framework.views import APIView

from core.common.api.options import IncludeIDsField


class ProjectAutoSchema(AutoSchema):
    def get_override_parameters(self):
        parameters = super().get_override_parameters()
        contract = getattr(self.view, f"{self.method.lower()}_contract", None)
        if contract is not None and contract.query is not None:
            return [contract.query, *parameters]
        return parameters

    def _process_override_parameters(self, direction="request"):
        parameters = super()._process_override_parameters(direction)
        contract = getattr(self.view, f"{self.method.lower()}_contract", None)
        if contract is None or contract.query is None:
            return parameters
        query = contract.query() if isinstance(contract.query, type) else contract.query
        explicit_names = {
            parameter.name
            for parameter in self.get_override_parameters()
            if isinstance(parameter, OpenApiParameter) and parameter.location == OpenApiParameter.QUERY
        }
        for name, field in query.fields.items():
            key = (name, OpenApiParameter.QUERY)
            if isinstance(field, IncludeIDsField) and name not in explicit_names and parameters.get(key):
                # IncludeIDsField maps to an array, but serializer expansion omits
                # parameter-level form encoding. Leave explicit annotations untouched.
                parameters[key]["style"] = "form"
                parameters[key]["explode"] = False
        return parameters

    def get_request_serializer(self):
        view = self.view
        method = self.method.upper()
        contract = getattr(view, f"{method.lower()}_contract", None)
        if contract is not None and contract.request is not None:
            request = contract.request
            return request() if isinstance(request, type) else request
        if (
            contract is not None
            and contract.request is None
            and not any(
                getattr(view, attribute, None) is not None
                for attribute in (
                    "request_serializer_class",
                    "create_serializer_class",
                    "update_serializer_class",
                    "serializer_class",
                )
            )
        ):
            return None
        serializer_class = None
        if method == "POST":
            serializer_class = getattr(view, "create_serializer_class", None)
        elif method in {"PUT", "PATCH"}:
            serializer_class = getattr(view, "update_serializer_class", None)
        if serializer_class is None:
            serializer_class = getattr(view, "request_serializer_class", None)
        if serializer_class:
            return serializer_class()
        return super().get_request_serializer()

    def get_response_serializers(self):
        view = self.view
        method = self.method.upper()
        view_name = view.__class__.__name__
        error_responses = {}
        get_errors = getattr(view, "get_openapi_error_responses", None)
        if callable(get_errors):
            error_responses = get_errors()
        contract = getattr(view, f"{method.lower()}_contract", None)
        if contract is not None:
            return {**contract.responses.document_configured(), **error_responses}
        list_serializer_class = getattr(view, "list_serializer_class", None)
        response_serializer_class = getattr(view, "response_serializer_class", None)
        reference_serializer_class = getattr(view, "serializer_class", None)
        if response_serializer_class is None:
            response_serializer_class = getattr(view, "read_serializer_class", None)

        if getattr(view, "openapi_list_response", False) and method == "GET" and reference_serializer_class:
            return {
                200: ResponseSchemaFactory.success(view_name, reference_serializer_class, many=True),
                **error_responses,
            }

        if list_serializer_class:
            if method == "GET":
                return {
                    200: ResponseSchemaFactory.polymorphic(
                    component_name=f"{view_name}ListResponseVariant",
                    response_serializers=[
                        ResponseSchemaFactory.success(view_name, list_serializer_class, many=True),
                        ResponseSchemaFactory.paginated(view_name, list_serializer_class),
                    ],
                    ),
                    **error_responses,
                }
            if method == "POST":
                return {200: ResponseSchemaFactory.success(view_name, list_serializer_class), **error_responses}

        if response_serializer_class and method in {"GET", "POST", "PUT", "PATCH"}:
            return {200: ResponseSchemaFactory.success(view_name, response_serializer_class), **error_responses}

        if method == "DELETE" and response_serializer_class:
            return {
                200: ResponseSchemaFactory.empty(f"{view_name}Delete"),
                **error_responses,
            }

        return super().get_response_serializers()

    def _get_response_bodies(self, direction="response"):
        if self.method.upper() == "DELETE" and getattr(self.view, "response_serializer_class", None):
            method = self.method
            self.method = "GET"
            try:
                return super()._get_response_bodies(direction)
            finally:
                self.method = method
        return super()._get_response_bodies(direction)

    def _get_serializer(self):
        view = self.view
        if (
            isinstance(view, APIView)
            and not isinstance(view, GenericAPIView)
            and not hasattr(view, "serializer_class")
            and not callable(getattr(view, "get_serializer", None))
            and not callable(getattr(view, "get_serializer_class", None))
        ):
            return OpenApiTypes.ANY
        return super()._get_serializer()

    def _tokenize_path(self):
        tokens = super()._tokenize_path()
        if tokens and tokens[0] == "api" and self.path.startswith("/api/"):
            # Remove only the transport mount when the base tokenizer retained it.
            # A configured path prefix may already have removed the mount.
            prefix_match = re.match(self.path_prefix, self.path, flags=re.IGNORECASE)
            if prefix_match is None or prefix_match.end() <= 1:
                return tokens[1:]
        return tokens

    def get_operation_id(self):
        operation_id = super().get_operation_id()
        path_parameters = re.findall(r"\{([\w-]+)\}", self.path)
        if path_parameters:
            operation_id += "_by_" + "_".join(path_parameters)
        return operation_id
