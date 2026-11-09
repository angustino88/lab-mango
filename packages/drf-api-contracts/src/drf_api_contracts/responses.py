from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from rest_framework import status
from rest_framework.response import Response

from .schema import ResponseSchemaFactory
from .serializers import EmptyPayloadSerializer, ProblemResponseEnvelopeSerializer
from .serializers import ProblemDetailSerializer as ProblemDetailSerializer
from .settings import DEFAULT_SETTINGS, ContractSettings
from .types import SerializerClass, SerializerDefinition


@dataclass(frozen=True, slots=True)
class ResponseContract:
    status_code: int
    schema: SerializerDefinition
    payload_serializer: SerializerClass | None = None
    many: bool = False
    is_paginated: bool = False
    settings: ContractSettings = DEFAULT_SETTINGS

    @classmethod
    def success(
        cls,
        name: str,
        payload_serializer: SerializerClass,
        *,
        many: bool = False,
        status_code: int = status.HTTP_200_OK,
        settings: ContractSettings = DEFAULT_SETTINGS,
    ) -> "ResponseContract":
        cls._validate_success_status(status_code)
        return cls(
            status_code,
            ResponseSchemaFactory.success(name, payload_serializer, many=many),
            payload_serializer,
            many,
            settings=settings,
        )

    @classmethod
    def ok(
        cls,
        name: str,
        payload_serializer: SerializerClass,
        *,
        many: bool = False,
        settings: ContractSettings = DEFAULT_SETTINGS,
    ) -> "ResponseContract":
        return cls.success(name, payload_serializer, many=many, settings=settings)

    @classmethod
    def created(
        cls,
        name: str,
        payload_serializer: SerializerClass,
        *,
        settings: ContractSettings = DEFAULT_SETTINGS,
    ) -> "ResponseContract":
        return cls.success(
            name,
            payload_serializer,
            status_code=status.HTTP_201_CREATED,
            settings=settings,
        )

    @classmethod
    def accepted(
        cls,
        name: str,
        payload_serializer: SerializerClass,
        *,
        settings: ContractSettings = DEFAULT_SETTINGS,
    ) -> "ResponseContract":
        return cls.success(
            name,
            payload_serializer,
            status_code=status.HTTP_202_ACCEPTED,
            settings=settings,
        )

    @classmethod
    def from_schema(
        cls,
        schema: SerializerDefinition,
        *,
        status_code: int = status.HTTP_200_OK,
        settings: ContractSettings = DEFAULT_SETTINGS,
    ) -> "ResponseContract":
        return cls(status_code=status_code, schema=schema, settings=settings)

    @classmethod
    def documented(
        cls,
        status_code: int,
        schema: SerializerDefinition,
        *,
        settings: ContractSettings = DEFAULT_SETTINGS,
    ) -> "ResponseContract":
        return cls.from_schema(schema, status_code=status_code, settings=settings)

    @classmethod
    def polymorphic(
        cls,
        component_name: str,
        response_serializers: Sequence[SerializerDefinition],
        *,
        status_code: int = status.HTTP_200_OK,
        settings: ContractSettings = DEFAULT_SETTINGS,
    ) -> "ResponseContract":
        return cls.documented(
            status_code,
            ResponseSchemaFactory.polymorphic(component_name, response_serializers),
            settings=settings,
        )

    @classmethod
    def problem(
        cls,
        status_code: int,
        schema: SerializerDefinition = ProblemResponseEnvelopeSerializer,
        *,
        settings: ContractSettings = DEFAULT_SETTINGS,
    ) -> "ResponseContract":
        if status_code < status.HTTP_400_BAD_REQUEST:
            raise ValueError("problem responses require a 4xx or 5xx status code")
        return cls(status_code=status_code, schema=schema, settings=settings)

    @classmethod
    def bad_request(cls, *, settings: ContractSettings = DEFAULT_SETTINGS) -> "ResponseContract":
        return cls.problem(status.HTTP_400_BAD_REQUEST, settings=settings)

    @classmethod
    def unauthorized(cls, *, settings: ContractSettings = DEFAULT_SETTINGS) -> "ResponseContract":
        return cls.problem(status.HTTP_401_UNAUTHORIZED, settings=settings)

    @classmethod
    def forbidden(cls, *, settings: ContractSettings = DEFAULT_SETTINGS) -> "ResponseContract":
        return cls.problem(status.HTTP_403_FORBIDDEN, settings=settings)

    @classmethod
    def not_found(cls, *, settings: ContractSettings = DEFAULT_SETTINGS) -> "ResponseContract":
        return cls.problem(status.HTTP_404_NOT_FOUND, settings=settings)

    @classmethod
    def conflict(cls, *, settings: ContractSettings = DEFAULT_SETTINGS) -> "ResponseContract":
        return cls.problem(status.HTTP_409_CONFLICT, settings=settings)

    @classmethod
    def paginated(
        cls,
        name: str,
        payload_serializer: SerializerClass,
        *,
        status_code: int = status.HTTP_200_OK,
        settings: ContractSettings = DEFAULT_SETTINGS,
    ) -> "ResponseContract":
        cls._validate_success_status(status_code)
        return cls(
            status_code=status_code,
            schema=ResponseSchemaFactory.paginated(name, payload_serializer),
            payload_serializer=payload_serializer,
            many=True,
            is_paginated=True,
            settings=settings,
        )

    @classmethod
    def empty(
        cls,
        name: str,
        *,
        status_code: int = status.HTTP_200_OK,
        settings: ContractSettings = DEFAULT_SETTINGS,
    ) -> "ResponseContract":
        cls._validate_success_status(status_code)
        return cls(
            status_code=status_code,
            schema=ResponseSchemaFactory.empty(name),
            payload_serializer=EmptyPayloadSerializer,
            settings=settings,
        )

    @classmethod
    def no_content(cls, *, settings: ContractSettings = DEFAULT_SETTINGS) -> "ResponseContract":
        return cls.documented(status.HTTP_204_NO_CONTENT, None, settings=settings)

    @staticmethod
    def _validate_success_status(status_code: int) -> None:
        if not status.HTTP_200_OK <= status_code < status.HTTP_400_BAD_REQUEST:
            raise ValueError("success responses require a 2xx or 3xx status code")

    def document(self) -> dict[int, SerializerDefinition]:
        return {self.status_code: self.schema}

    @staticmethod
    def document_many(*contracts: "ResponseContract") -> dict[int, SerializerDefinition]:
        documented: dict[int, SerializerDefinition] = {}
        for contract in contracts:
            if contract.status_code in documented:
                raise ValueError(f"duplicate response status code: {contract.status_code}")
            documented.update(contract.document())
        return documented

    def respond(self, data: Any, *, headers: Mapping[str, str] | None = None) -> Response:
        if self.is_paginated:
            raise TypeError("paginated contracts require respond_page()")
        return Response({self.settings.success_key: data}, status=self.status_code, headers=headers)

    def serialize(
        self,
        instance: Any,
        serializer_class: SerializerClass | None = None,
        *,
        many: bool | None = None,
        context: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        if self.is_paginated:
            raise TypeError("paginated contracts require respond_page()")
        serializer_class = serializer_class or self.payload_serializer
        if serializer_class is None:
            raise TypeError("serialize() requires a success contract with a payload serializer")
        serializer = serializer_class(
            instance=instance,
            many=self.many if many is None else many,
            context=context or {},
        )
        return self.respond(serializer.data, headers=headers)

    def respond_data(
        self,
        data: Any,
        *,
        context: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        if self.is_paginated:
            raise TypeError("paginated contracts require respond_page() with explicit page metadata")
        if self.payload_serializer is not None:
            serializer = self.payload_serializer(
                data=data,
                many=self.many,
                context=context or {},
            )
            serializer.is_valid(raise_exception=True)
        return self.respond(data, headers=headers)

    def respond_page(
        self,
        total_count: int,
        results: Any,
        *,
        page: int = 1,
        page_size: int | None = None,
        next: str | None = None,
        previous: str | None = None,
        context: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        if not self.is_paginated or self.payload_serializer is None:
            raise TypeError("respond_page() requires a paginated success contract")
        if total_count < 0:
            raise ValueError("total_count must be non-negative")
        if page < 1:
            raise ValueError("page must be at least 1")
        serializer = self.payload_serializer(instance=results, many=True, context=context or {})
        current_page_size = (len(serializer.data) or 1) if page_size is None else page_size
        if current_page_size < 1:
            raise ValueError("page_size must be positive")
        return Response(
            {
                self.settings.success_key: serializer.data,
                self.settings.pagination_meta_key: {
                    "pagination": {
                        "count": total_count,
                        "page": page,
                        "page_size": current_page_size,
                        "next": next,
                        "previous": previous,
                    }
                },
            },
            status=self.status_code,
            headers=dict(headers or {}),
        )

    def respond_problem(
        self,
        *,
        code: Any = None,
        detail: Any = None,
        errors: Any = None,
        request_id: str = "unknown",
    ) -> Response:
        if self.status_code < status.HTTP_400_BAD_REQUEST:
            raise ValueError("problem responses require a 4xx or 5xx status code")
        error_code = self.settings.code_resolver(code) if code else "api_error"
        return Response(
            {
                "error": {
                    "code": error_code,
                    "message": self.settings.problem_detail_resolver(detail, code, self.status_code),
                    "details": _error_details(errors),
                    "request_id": request_id,
                }
            },
            status=self.status_code,
        )


def _error_details(errors: Any, prefix: str = "") -> list[dict[str, Any]]:
    if hasattr(errors, "code") and not isinstance(errors, Mapping):
        return [{"field": prefix or None, "code": str(errors.code), "message": str(errors)}]
    if isinstance(errors, Mapping):
        if set(errors) == {"field", "code", "message"}:
            return [
                {
                    "field": str(errors["field"]),
                    "code": str(errors["code"]),
                    "message": str(errors["message"]),
                }
            ]
        details: list[dict[str, Any]] = []
        for field, value in errors.items():
            path = f"{prefix}.{field}" if prefix else str(field)
            details.extend(_error_details(value, path))
        return details
    if isinstance(errors, (list, tuple)):
        details = []
        for index, value in enumerate(errors):
            if prefix and hasattr(value, "code"):
                details.extend(_error_details(value, prefix))
            else:
                path = f"{prefix}[{index}]" if prefix else str(index)
                details.extend(_error_details(value, path))
        return details
    if errors is None:
        return []
    return [{"field": prefix or None, "code": str(getattr(errors, "code", "invalid")), "message": str(errors)}]
