"""Shared implementation for catalog and selector API (ADR 002).

Provides the unified selector contract {id, sku, name}, ETag caching,
cap enforcement (cap + 1 -> 400 too_many_results), size-class validation,
and include_ids support.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from django.db.models import QuerySet
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.extensions import OpenApiSerializerFieldExtension
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_serializer
from rest_framework import serializers, status
from rest_framework.exceptions import ErrorDetail
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.common.api.permissions import HasAPIKeyAccess

from .command_views import FeatureAPIView
from .filtering import CSVField, PositiveIDField

OPTIONS_MAX_RESULTS = 1000


class SizeClass(StrEnum):
    """Catalog size classification for selector endpoints (OPT-11)."""

    SMALL = "small"
    LARGE = "large"


@extend_schema_serializer(component_name="CatalogOption")
class CatalogOptionSerializer(serializers.Serializer):
    """Standard selector dropdown item: exactly {id, sku, name} (OPT-2, OPT-4)."""

    id = serializers.IntegerField(read_only=True)
    sku = serializers.CharField(allow_null=True, read_only=True)
    name = serializers.CharField(read_only=True)


@extend_schema_serializer(component_name="CatalogOptionList")
class CatalogOptionListSerializer(serializers.Serializer):
    """Enveloped list of selector options."""

    data = CatalogOptionSerializer(many=True, read_only=True)


class IncludeIDsField(CSVField):
    """Retired values parameter: comma-separated positive integers, unique, max 50 (OPT-10)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(PositiveIDField(), max_items=50, **kwargs)


class IncludeIDsFieldExtension(OpenApiSerializerFieldExtension):
    target_class = IncludeIDsField

    def map_serializer_field(self, auto_schema: Any, direction: str) -> dict[str, Any]:
        return {
            "type": "array",
            "items": {"type": "integer", "minimum": 1},
            "maxItems": 50,
            "uniqueItems": True,
        }


class OptionsQueryMixin(serializers.Serializer):
    """Mixin adding q (1 to 100 characters, no blank) and include_ids to query serializers."""

    q = serializers.CharField(
        required=False,
        min_length=1,
        max_length=100,
        allow_blank=False,
        help_text="Search text (1 to 100 characters).",
    )
    include_ids = IncludeIDsField(
        required=False,
        help_text="Comma-separated positive integers (at most 50) of retired rows to include.",
    )


class OptionsAPIView(FeatureAPIView):
    """Shared base view for dropdown selector endpoints (ADR 002).

    Validates query parameters, enforces the size class and result cap,
    calls the feature's query selector, handles ETag generation / 304 Not Modified,
    and returns {"data": [{"id": ..., "sku": ..., "name": ...}]}.
    """

    permission_classes = [HasAPIKeyAccess | IsAuthenticated]
    http_method_names = ["get", "options", "head"]
    size_class: SizeClass = SizeClass.SMALL
    required_any: tuple[str, ...] | None = None
    max_results: int = OPTIONS_MAX_RESULTS
    owner: str | None = None
    query_serializer: type[serializers.Serializer] | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "query_serializer", None) is not None and not hasattr(cls, "get_contract"):
            cls.get_contract = OperationContract(
                query=cls.query_serializer,
                success=ResponseContract(
                    status_code=200,
                    schema=CatalogOptionListSerializer,
                    payload_serializer=CatalogOptionSerializer,
                    many=True,
                ),
                not_modified=ResponseContract.empty("NotModified", status_code=304),
                bad_request=ResponseContract.bad_request(),
                forbidden=ResponseContract.problem(403),
            )

        schema_kwargs: dict[str, Any] = {
            "responses": {
                200: OpenApiResponse(
                    response=CatalogOptionListSerializer,
                    description="Standard selector options list",
                ),
                400: OpenApiResponse(
                    response=ResponseContract.bad_request().schema,
                    description="Invalid selector query parameters (invalid_query) or result cap exceeded (too_many_results).",
                ),
                304: OpenApiResponse(description="Not modified"),
                403: OpenApiResponse(
                    response=ResponseContract.forbidden().schema,
                    description="Access denied by the existing API-key or authenticated-user permission policy.",
                ),
            },
            "description": getattr(cls, "schema_description", None),
        }
        if cls.owner:
            schema_kwargs["extensions"] = {"x-owner": cls.owner}
        if getattr(cls, "schema_tags", None):
            schema_kwargs["tags"] = list(cls.schema_tags)

        extend_schema(**schema_kwargs)(cls)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> QuerySet | list[dict[str, Any]]:
        """Return matching selector items or QuerySet for the actor and filters.

        Must be implemented by concrete feature options views.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement select().")

    def validate_options_query(self, request: Any) -> tuple[dict[str, Any] | None, Response | None]:
        """Validate options query parameters against schema and size class rules."""
        serializer_class = self.query_serializer
        if serializer_class is None:
            return {}, None

        query_params = getattr(request, "query_params", getattr(request, "GET", {}))

        # 1. Unknown parameter check: No page, page_size, search, ordering allowed on /options
        known_keys = set(serializer_class().fields.keys())
        provided_keys = set(query_params.keys())
        unknown_keys = provided_keys - known_keys
        if unknown_keys:
            return None, self.respond_problem(
                "bad_request",
                code="invalid_query",
                errors={
                    key: [ErrorDetail("Unknown query parameter.", code="unknown_field")]
                    for key in sorted(unknown_keys)
                },
            )

        # 2. Repeated parameter check
        query_errors: dict[str, list[ErrorDetail]] = {}
        for key in known_keys & provided_keys:
            if hasattr(query_params, "getlist") and len(query_params.getlist(key)) > 1:
                query_errors[key] = [ErrorDetail("This parameter must not be repeated.", code="invalid_query")]
            elif query_params.get(key) == "":
                query_errors[key] = [ErrorDetail("Empty value is not allowed.", code="invalid_query")]

        if query_errors:
            return None, self.respond_problem(
                "bad_request",
                code="invalid_query",
                errors=query_errors,
            )

        # 3. Serializer validation - use plain dict to avoid DRF QueryDict HTML checkbox defaulting
        data = {k: query_params.get(k) for k in query_params}
        serializer = serializer_class(
            data=data,
            context={"request": request},
        )
        if not serializer.is_valid():
            return None, self.respond_problem(
                "bad_request",
                code="invalid_query",
                errors=serializer.errors,
            )

        validated = dict(serializer.validated_data)

        # 4. SizeClass check for LARGE catalogs
        if self.size_class == SizeClass.LARGE and self.required_any:
            req_any = self.required_any
            has_required = any(validated.get(k) is not None and validated.get(k) != "" for k in req_any)
            if not has_required:
                fields_str = ", ".join(sorted(req_any))
                return None, self.respond_problem(
                    "bad_request",
                    code="invalid_query",
                    detail=f"At least one of the following filters is required: {fields_str}.",
                    errors={
                        k: [
                            ErrorDetail(
                                f"Required filter missing. One of {fields_str} must be provided.", code="required"
                            )
                        ]
                        for k in sorted(req_any)
                    },
                )

        return validated, None

    def _apply_etag_and_caching(self, request: Any, response: Response) -> Response:
        """Compute strong ETag over serialized response body and handle 304."""
        rendered = json.dumps(response.data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        etag = f'"{hashlib.sha256(rendered).hexdigest()}"'

        if_none_match = request.headers.get("If-None-Match")
        if if_none_match:
            client_etags = [t.strip() for t in if_none_match.split(",")]
            clean_client = [t[2:] if t.startswith("W/") else t for t in client_etags]
            clean_etag = etag.strip('"')
            if etag in client_etags or "*" in client_etags or any(t.strip('"') == clean_etag for t in clean_client):
                not_modified = Response(status=status.HTTP_304_NOT_MODIFIED)
                not_modified["ETag"] = etag
                not_modified["Cache-Control"] = "private, no-cache"
                not_modified["Vary"] = "Accept-Language"
                return not_modified

        response["ETag"] = etag
        response["Cache-Control"] = "private, no-cache"
        response["Vary"] = "Accept-Language"
        return response

    def handle_get(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        filters, error = self.validate_options_query(request)
        if error is not None:
            error["Cache-Control"] = "no-store"
            return error

        rows = self.select(actor=self.acting_user, filters=filters or {})

        cap = self.max_results
        if isinstance(rows, QuerySet):
            items = list(rows[: cap + 1])
        else:
            items = list(rows)

        if len(items) > cap:
            resp = self.respond_problem(
                "bad_request",
                code="too_many_results",
                detail=f"More than {cap} results match. Narrow the filters.",
            )
            resp["Cache-Control"] = "no-store"
            return resp

        response = self.respond(items)
        return self._apply_etag_and_caching(request, response)


__all__ = [
    "CatalogOptionListSerializer",
    "CatalogOptionSerializer",
    "IncludeIDsField",
    "IncludeIDsFieldExtension",
    "OPTIONS_MAX_RESULTS",
    "OptionsAPIView",
    "OptionsQueryMixin",
    "SizeClass",
]
