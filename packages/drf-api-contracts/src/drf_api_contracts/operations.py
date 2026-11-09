from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response

from .responses import ResponseContract
from .types import SerializerDefinition


@dataclass(frozen=True, slots=True, init=False)
class ResponseSet:
    success: ResponseContract
    alternates: Mapping[str, ResponseContract]
    problems: Mapping[str, ResponseContract]

    def __init__(
        self,
        success: ResponseContract | SerializerDefinition,
        *,
        alternates: Mapping[str, ResponseContract] | None = None,
        **problems: ResponseContract,
    ) -> None:
        if not isinstance(success, ResponseContract):
            success = ResponseContract.from_schema(success)
        alternate_successes = alternates or {}
        self._validate_alternates(alternate_successes)
        self._validate_success("success", success)
        for name, contract in alternate_successes.items():
            self._validate_success(name, contract)
        for name, contract in problems.items():
            if contract.status_code < status.HTTP_400_BAD_REQUEST:
                raise ValueError(f"problem response must use a 4xx or 5xx status: {name}")
        object.__setattr__(self, "success", success)
        object.__setattr__(self, "alternates", alternate_successes)
        object.__setattr__(self, "problems", problems)

    @staticmethod
    def _validate_alternates(alternates: Mapping[str, ResponseContract]) -> None:
        for name in alternates:
            if name == "success" or not name.isidentifier():
                raise ValueError("alternate response names must be Python identifiers other than 'success'")

    @staticmethod
    def _validate_success(name: str, contract: ResponseContract) -> None:
        if not isinstance(contract, ResponseContract):
            raise TypeError(f"response contract must be a ResponseContract: {name}")
        if contract.status_code >= status.HTTP_400_BAD_REQUEST:
            raise ValueError(f"success response must use a 2xx or 3xx status: {name}")

    def __getattr__(self, name: str) -> ResponseContract | None:
        return self.alternates.get(name) or self.problems.get(name)

    def document(self, *names: str) -> dict[int, SerializerDefinition]:
        return ResponseContract.document_many(*(self.get(name) for name in ("success", *names)))

    def document_configured(self) -> dict[int, SerializerDefinition]:
        return ResponseContract.document_many(self.success, *self.alternates.values(), *self.problems.values())

    def get(self, name: str) -> ResponseContract:
        contract = self.success if name == "success" else self.alternates.get(name) or self.problems.get(name)
        if contract is None:
            raise ValueError(f"response contract is not configured: {name}")
        return contract


@dataclass(frozen=True, slots=True)
class OperationContract:
    responses: ResponseSet
    request: SerializerDefinition | None = None
    query: SerializerDefinition | None = None
    tags: tuple[str, ...] = ()
    parameters: tuple[OpenApiParameter, ...] = ()

    def __init__(
        self,
        success: ResponseContract | SerializerDefinition | None = None,
        *,
        request: SerializerDefinition | None = None,
        query: SerializerDefinition | None = None,
        tags: tuple[str, ...] | list[str] | None = None,
        parameters: tuple[OpenApiParameter, ...] | list[OpenApiParameter] | None = None,
        responses: ResponseSet | None = None,
        **named_responses: ResponseContract,
    ) -> None:
        if responses is not None:
            if success is not None or named_responses:
                raise ValueError("use either responses or success and named responses, not both")
            response_set = responses
        else:
            if success is None:
                raise TypeError("success response must be configured")
            alternates = {
                name: contract
                for name, contract in named_responses.items()
                if contract.status_code < status.HTTP_400_BAD_REQUEST
            }
            problems = {
                name: contract
                for name, contract in named_responses.items()
                if contract.status_code >= status.HTTP_400_BAD_REQUEST
            }
            configured_statuses = {contract.status_code for contract in problems.values()}
            success_contract = success if isinstance(success, ResponseContract) else ResponseContract.from_schema(success)
            if request is not None and status.HTTP_400_BAD_REQUEST not in configured_statuses:
                problems["bad_request"] = ResponseContract.bad_request()
                configured_statuses.add(status.HTTP_400_BAD_REQUEST)
            if request is not None and status.HTTP_422_UNPROCESSABLE_ENTITY not in configured_statuses:
                problems["validation_error"] = ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY)
                configured_statuses.add(status.HTTP_422_UNPROCESSABLE_ENTITY)
            if (query is not None or success_contract.is_paginated) and status.HTTP_400_BAD_REQUEST not in configured_statuses:
                problems["bad_request"] = ResponseContract.bad_request()
            response_set = ResponseSet(success, alternates=alternates, **problems)
        object.__setattr__(self, "responses", response_set)
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "tags", tuple(tags or ()))
        object.__setattr__(self, "parameters", tuple(parameters or ()))

    def schema(self, **kwargs: Any):
        if self.tags and "tags" not in kwargs:
            kwargs["tags"] = list(self.tags)
        parameters = ([self.query] if self.query is not None else []) + list(self.parameters)
        return extend_schema(
            request=self.request,
            parameters=parameters or None,
            responses=self.responses.document_configured(),
            **kwargs,
        )

    def respond(self, instance: Any, *, many: bool | None = None, context: Mapping[str, Any] | None = None) -> Response:
        return self.responses.success.serialize(instance, many=many, context=context)

    def respond_data(self, data: Any, *, context: Mapping[str, Any] | None = None) -> Response:
        return self.responses.success.respond_data(data, context=context)

    def respond_problem(self, name: str, **kwargs: Any) -> Response:
        return self.responses.get(name).respond_problem(**kwargs)

    def serializer(
        self,
        *,
        data: Any,
        instance: Any = None,
        partial: bool = False,
        context: Mapping[str, Any] | None = None,
    ) -> serializers.BaseSerializer:
        if self.request is None or not isinstance(self.request, type):
            raise TypeError("serializer() requires a request serializer class")
        return self.request(instance=instance, data=data, partial=partial, context=context or {})

    def query_serializer(self, *, data: Any, context: Mapping[str, Any] | None = None) -> serializers.BaseSerializer:
        if self.query is None or not isinstance(self.query, type):
            raise TypeError("query_serializer() requires a query serializer class")
        return self.query(data=data, context=context or {})
