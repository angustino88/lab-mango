"""Base API views for endpoints with declared response contracts."""

import asyncio
import inspect
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote

from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.shortcuts import get_object_or_404
from django.utils.functional import classproperty
from drf_api_contracts import OperationContract, ResponseSet
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail
from rest_framework.response import Response

from .correlation import get_request_id
from .pagination import ResultsSetPagination
from .search import DEPRECATED_SEARCH_PARAM

RESOURCE_FIELD_IMMUTABLE = "resource_field_immutable"


class AppAPIView(APIView):
    responses: ResponseSet | None = None
    schema_tags: tuple[str, ...] | list[str] | None = None

    @classproperty
    def view_is_async(cls) -> bool:
        return True

    def finalize_response(self, request: Any, response: Any, *args: Any, **kwargs: Any) -> Any:
        response = super().finalize_response(request, response, *args, **kwargs)
        query_params = getattr(request, "query_params", None)
        if query_params is not None and DEPRECATED_SEARCH_PARAM in query_params:
            # CMP-3: a deprecated request field is still accepted and announced on the response.
            response["Deprecation"] = "true"
        return response

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        method = request.method.lower() if hasattr(request, "method") else ""
        if method in self.http_method_names:
            handler = getattr(self, method, None)
            if handler is not None and not asyncio.iscoroutinefunction(handler):
                unwrapped = inspect.unwrap(handler)
                if asyncio.iscoroutinefunction(unwrapped):
                    inspect.markcoroutinefunction(handler)
        return super().dispatch(request, *args, **kwargs)

    async def _dispatch_sync_handler(
        self,
        method: str,
        request: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        handler = getattr(self, f"handle_{method}", None)
        if handler is None:
            return self.http_method_not_allowed(request, *args, **kwargs)
        return await sync_to_async(handler)(request, *args, **kwargs)

    def _allowed_methods(self) -> list[str]:
        """Advertise only the HTTP methods this view actually implements.

        Every AppAPIView inherits the five base dispatchers, so without this the
        ``Allow`` header and the OpenAPI schema list methods the view does not
        implement. A method counts as implemented when a subclass defines
        ``handle_<method>`` or overrides the base dispatcher itself.
        """
        allowed = []
        for method in self.http_method_names:
            if method == "options":
                continue
            base_dispatcher = AppAPIView.__dict__.get(method)
            if (
                getattr(self, f"handle_{method}", None) is not None
                or getattr(type(self), method, None) is not base_dispatcher
            ):
                allowed.append(method.upper())
        return [*allowed, "OPTIONS"]

    async def get(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        return await self._dispatch_sync_handler("get", request, *args, **kwargs)

    async def post(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        return await self._dispatch_sync_handler("post", request, *args, **kwargs)

    async def put(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        return await self._dispatch_sync_handler("put", request, *args, **kwargs)

    async def patch(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        return await self._dispatch_sync_handler("patch", request, *args, **kwargs)

    async def delete(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        return await self._dispatch_sync_handler("delete", request, *args, **kwargs)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        schemas = {
            method: contract.schema()
            for method in cls.http_method_names
            if method in cls.__dict__
            if (contract := getattr(cls, f"{method}_contract", None)) is not None
        }
        if schemas:
            from drf_spectacular.utils import extend_schema, extend_schema_view

            if any(not hasattr(cls, f"handle_{method}") for method in schemas):
                for method_name, method_schema in schemas.items():
                    method = getattr(cls, method_name)
                    if not hasattr(cls, f"handle_{method_name}"):
                        setattr(cls, method_name, method_schema(method))
                async_schemas = {
                    method: method_schema
                    for method, method_schema in schemas.items()
                    if hasattr(cls, f"handle_{method}")
                }
                if async_schemas:
                    extend_schema_view(**async_schemas)(cls)
            else:
                extend_schema_view(**schemas)(cls)
        if cls.schema_tags:
            from drf_spectacular.utils import extend_schema

            extend_schema(tags=list(cls.schema_tags))(cls)

    def operation(self, method: str | None = None) -> OperationContract:
        method = method or self.request.method.lower()
        contract = getattr(type(self), f"{method.lower()}_contract", None)
        if contract is None:
            raise TypeError(f"{type(self).__name__}.{method.lower()}_contract must be configured")
        return contract

    def success_contract(self):
        """Return the active success response contract for this view."""
        request_method = getattr(getattr(self, "request", None), "method", None)
        operation = getattr(type(self), f"{request_method.lower()}_contract", None) if request_method else None
        if operation is not None:
            return operation.responses.success
        if self.responses is not None:
            return self.responses.success
        raise TypeError(f"{type(self).__name__} must configure a response contract")

    def respond(self, instance: Any, *, many: bool | None = None) -> Response:
        contract = self.success_contract()
        if contract.is_paginated:
            return self.list_response_sync(instance)
        response = contract.serialize(
            instance,
            many=many,
            context={"request": self.request},
        )
        return self._add_created_location(response)

    def respond_problem(self, name: str, **kwargs: Any) -> Response:
        request_method = getattr(getattr(self, "request", None), "method", None)
        operation = self.operation(request_method) if request_method else None
        if operation is not None:
            contract = operation.responses.get(name)
            kwargs.setdefault("request_id", get_request_id(self.request))
            response = contract.respond_problem(**kwargs)
            if response.status_code == 401:
                response.setdefault("WWW-Authenticate", 'Bearer realm="api"')
            return response
        if self.responses is not None:
            contract = self.responses.get(name)
            kwargs.setdefault("request_id", get_request_id(self.request))
            response = contract.respond_problem(**kwargs)
            if response.status_code == 401:
                response.setdefault("WWW-Authenticate", 'Bearer realm="api"')
            return response
        raise TypeError(f"{type(self).__name__} must configure a response contract")

    def respond_data(self, data: Any) -> Response:
        """Respond with ``data`` rendered by the contract's payload serializer.

        The body is the serializer's representation, so the wire is the documented schema (response standard
        DOC-4). Contracts without a payload serializer (schema-only) return ``data`` unchanged.
        """
        contract = self.success_contract()
        if contract.is_paginated:
            return self.list_response_sync(data)
        if contract.payload_serializer is not None:
            response = contract.serialize(data, context={"request": self.request})
        else:
            response = contract.respond_data(data, context={"request": self.request})
        return self._add_created_location(response)

    def _add_created_location(self, response: Response) -> Response:
        payload = response.data.get("data") if isinstance(response.data, Mapping) else None
        request_path = getattr(self.request, "path", "")
        if (
            response.status_code == 201
            and "/actions/" not in request_path
            and isinstance(payload, Mapping)
            and payload.get("id") is not None
        ):
            location_path = f"{request_path.rstrip('/')}/{quote(str(payload['id']), safe='')}"
            response["Location"] = self.request.build_absolute_uri(location_path)
        return response

    async def respond_async(self, operation: Callable[[], Response]) -> Response:
        """Build a DRF response from synchronous request work."""
        return await sync_to_async(operation)()

    async def async_respond_data(self, data: Any) -> Response:
        return await self.respond_async(lambda: self.respond_data(data))

    async def async_respond_problem(self, name: str, **kwargs: Any) -> Response:
        return await self.respond_async(lambda: self.respond_problem(name, **kwargs))

    def validate_request(
        self,
        *,
        serializer_class: Any = None,
        instance: Any = None,
        data: Any = None,
        partial: bool = False,
    ) -> tuple[Any | None, Response | None]:
        operation = getattr(type(self), f"{self.request.method.lower()}_contract", None)
        serializer_data = self.request.data if data is None else data
        context = {"request": self.request}
        if serializer_class is None:
            if operation is None:
                raise TypeError(f"{type(self).__name__} must declare an operation contract for request validation")
            serializer = operation.serializer(
                instance=instance,
                data=serializer_data,
                partial=partial,
                context=context,
            )
        else:
            serializer = serializer_class(
                instance=instance,
                data=serializer_data,
                partial=partial,
                context=context,
            )
        field_errors = _strict_input_errors(serializer, serializer_data)
        if field_errors:
            problem_name = "bad_request"
            if operation is not None:
                problem_name = next(
                    (
                        name
                        for name, contract in operation.responses.problems.items()
                        if contract.status_code == 422
                    ),
                    "bad_request",
                )
            return None, self.respond_problem(problem_name, code="validation_failed", errors=field_errors)
        if serializer.is_valid():
            return serializer, None
        if (
            operation is not None
            and serializer.errors.get("code")
            and serializer.errors["code"][0] == RESOURCE_FIELD_IMMUTABLE
        ):
            return None, self.respond_problem(
                "conflict",
                code=RESOURCE_FIELD_IMMUTABLE,
                detail=str(serializer.errors.get("detail", "A resource identifier cannot be changed.")),
                errors={},
            )
        response_name = "bad_request"
        if operation is not None:
            response_name = next(
                (
                    name
                    for name, contract in operation.responses.problems.items()
                    if contract.status_code == 422
                ),
                "bad_request",
            )
        return None, self.respond_problem(
            response_name,
            code="validation_failed",
            errors=serializer.errors,
        )

    def validate_query(self) -> tuple[Mapping[str, Any] | None, Response | None]:
        operation = self.operation()
        serializer = operation.query_serializer(
            data=self.request.query_params,
            context={"request": self.request},
        )
        known_query_keys = set(serializer.fields) | {"page", "page_size"}
        unknown_query_keys = set(self.request.query_params.keys()) - known_query_keys
        if unknown_query_keys:
            if operation.responses.bad_request is None:
                raise TypeError(f"{type(self).__name__} must declare a bad_request response for query validation")
            return None, self.respond_problem(
                "bad_request",
                code="invalid_query",
                errors={
                    key: [ErrorDetail("Unknown filter or ordering field.", code="invalid_query")]
                    for key in sorted(unknown_query_keys)
                },
            )
        query_errors = {}
        for key in known_query_keys & set(self.request.query_params.keys()):
            values = self.request.query_params.getlist(key)
            if len(values) > 1:
                query_errors[key] = [ErrorDetail("This parameter must not be repeated.", code="invalid_query")]
        for key in ("page", "page_size"):
            if key not in self.request.query_params:
                continue
            raw_value = self.request.query_params.get(key, "")
            # Match DRF IntegerField's bounded conversion and never pass an
            # attacker-sized decimal to Python's int conversion or the paginator.
            try:
                if (
                    len(raw_value) > serializers.IntegerField.MAX_STRING_LENGTH
                    or not raw_value.isascii()
                    or not raw_value.isdecimal()
                ):
                    raise ValueError
                value = int(raw_value)
            except ValueError:
                query_errors[key] = [ErrorDetail("Enter a positive integer.", code="invalid_query")]
                continue
            if value < 1:
                query_errors[key] = [ErrorDetail("Enter a positive integer.", code="invalid_query")]
            elif key == "page_size":
                pagination_class = getattr(self, "pagination_class", ResultsSetPagination)
                maximum = getattr(pagination_class, "max_page_size", 100) or 100
                if value > maximum:
                    query_errors[key] = [
                        ErrorDetail(f"Ensure this value is less than or equal to {maximum}.", code="max_value")
                    ]
        if query_errors:
            return None, self.respond_problem(
                "bad_request",
                code="invalid_query",
                errors=query_errors,
            )
        if serializer.is_valid():
            return serializer.validated_data, None
        return None, self.respond_problem(
            "bad_request",
            code="validation_failed",
            errors=serializer.errors,
        )

    def _responses(self) -> ResponseSet:
        if self.responses is None:
            raise TypeError(f"{type(self).__name__}.responses must be configured")
        return self.responses


def _strict_input_errors(serializer: Any, data: Any) -> dict[str, Any]:
    """Reject undeclared/read-only keys and values with coercible JSON types."""
    if isinstance(serializer, serializers.Field) and not isinstance(serializer, serializers.BaseSerializer) and not isinstance(
        serializer,
        (serializers.ListField, serializers.DictField),
    ):
        expected = _expected_json_type(serializer)
        if expected is None or data is None:
            return {}
        valid_type = type(data) is expected if expected in (bool, int) else isinstance(data, expected)
        if expected == (int, float) and isinstance(data, bool):
            valid_type = False
        if not valid_type:
            return {"$": [ErrorDetail("Value has the wrong JSON type.", code="invalid_type")]}
        return {}

    if isinstance(serializer, serializers.ListSerializer):
        if not isinstance(data, list):
            return {}
        return {
            str(index): nested_errors
            for index, item in enumerate(data)
            if (nested_errors := _strict_input_errors(serializer.child, item))
        }

    if not isinstance(data, Mapping) or not hasattr(serializer, "fields"):
        return {}

    errors: dict[str, Any] = {}
    for key, value in data.items():
        field = serializer.fields.get(key)
        if field is None:
            errors[key] = [ErrorDetail("Unknown field.", code="unknown_field")]
            continue
        if field.read_only:
            errors[key] = [ErrorDetail("This field is read-only.", code="read_only_field")]
            continue
        if value is None:
            if not field.allow_null:
                errors[key] = [ErrorDetail("This field may not be null.", code="null_not_allowed")]
            continue

        expected = _expected_json_type(field)

        if expected is not None:
            is_valid_type = type(value) is expected if expected in (bool, int) else isinstance(value, expected)
            if expected == (int, float) and isinstance(value, bool):
                is_valid_type = False
            if not is_valid_type:
                errors[key] = [ErrorDetail("Value has the wrong JSON type.", code="invalid_type")]
                continue

        if isinstance(field, (serializers.ListField, serializers.ListSerializer)):
            child_errors = {
                str(index): nested_errors
                for index, item in enumerate(value)
                if (nested_errors := _strict_input_errors(field.child, item))
            }
            if child_errors:
                errors[key] = child_errors
        elif isinstance(field, serializers.DictField) and field.child is not None:
            child_errors = {}
            for child_key, child_value in value.items():
                nested_errors = _strict_input_errors(field.child, child_value)
                if nested_errors:
                    child_errors[child_key] = nested_errors
            if child_errors:
                errors[key] = child_errors
        elif isinstance(field, serializers.BaseSerializer) and hasattr(field, "fields"):
            nested_errors = _strict_input_errors(field, value)
            if nested_errors:
                errors[key] = nested_errors
    return errors


def _expected_json_type(field: Any) -> type | tuple[type, ...] | None:
    if isinstance(field, serializers.BooleanField):
        return bool
    if isinstance(field, (serializers.IntegerField, serializers.PrimaryKeyRelatedField)):
        return int
    if isinstance(field, serializers.DecimalField):
        return str
    if isinstance(field, serializers.FloatField):
        return (int, float)
    if isinstance(
        field,
        (
            serializers.CharField,
            serializers.ChoiceField,
            serializers.UUIDField,
            serializers.DateField,
            serializers.DateTimeField,
            serializers.TimeField,
        ),
    ):
        return str
    if isinstance(field, serializers.ListField):
        return list
    if isinstance(field, serializers.DictField):
        return Mapping
    return None


class AppDetailAPIView(AppAPIView):
    async def get_object(self, model: Any, **lookup: Any) -> Any:
        return await sync_to_async(get_object_or_404)(model, **lookup)

    async def update(
        self,
        instance: Any,
        data: Any,
        *,
        partial: bool = False,
    ) -> tuple[Any | None, Response | None]:
        serializer, error = self.validate_request(instance=instance, data=data, partial=partial)
        if error is not None:
            return None, error
        return await sync_to_async(serializer.save)(), None


class AppListAPIView(AppAPIView):
    pagination_class = ResultsSetPagination
    paginate_by_default = True

    def list_response_sync(self, queryset: Any) -> Response:
        if not self.paginate_by_default:
            return self.respond(queryset)

        if self.request.query_params:
            operation = self.operation()
            serializer_class = operation.query if operation.query is not None else None
            allowed = set(serializer_class().fields) if serializer_class is not None else set()
            allowed.update(("page", "page_size"))
            unknown = set(self.request.query_params.keys()) - allowed
            if unknown:
                return self.respond_problem(
                    "bad_request",
                    code="invalid_query",
                    errors={key: [ErrorDetail("Unknown query parameter.", code="invalid_query")] for key in sorted(unknown)},
                )
            for key in allowed & set(self.request.query_params.keys()):
                values = self.request.query_params.getlist(key)
                if len(values) > 1:
                    return self.respond_problem(
                        "bad_request",
                        code="invalid_query",
                        errors={key: [ErrorDetail("This parameter must not be repeated.", code="invalid_query")]},
                    )
            for key in ("page", "page_size"):
                raw_value = self.request.query_params.get(key)
                if raw_value is None:
                    continue
                pagination_class = self.pagination_class
                maximum = getattr(pagination_class, "max_page_size", 100) or 100
                if not raw_value.isascii() or not raw_value.isdecimal() or int(raw_value) < 1:
                    return self.respond_problem(
                        "bad_request",
                        code="invalid_query",
                        errors={key: [ErrorDetail("Enter a positive integer.", code="invalid_query")]},
                    )
                if key == "page_size" and int(raw_value) > maximum:
                    return self.respond_problem(
                        "bad_request",
                        code="invalid_query",
                        errors={key: [ErrorDetail(f"Ensure this value is less than or equal to {maximum}.", code="max_value")]},
                    )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        serializer_class = self.operation().responses.success.payload_serializer or getattr(
            self,
            "list_serializer_class",
            None,
        )
        if serializer_class is None:
            raise TypeError("list responses require a success payload serializer")
        serializer = serializer_class(
            page,
            many=True,
            context={"request": self.request},
        )
        return paginator.get_paginated_response(serializer.data)

    async def list_response(self, queryset: Any) -> Response:
        if not self.paginate_by_default:
            return await sync_to_async(self.respond)(queryset)

        return await sync_to_async(self.list_response_sync)(queryset)


