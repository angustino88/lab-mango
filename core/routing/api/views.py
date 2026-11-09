"""HTTP views for the private routing sync API with OpenAPI schema contracts."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    PermissionDenied,
)
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.correlation import REQUEST_ID_HEADER, get_request_id
from core.routing.api.authentication import (
    IsRoutingSyncAuthenticated,
    RoutingSyncAuthentication,
    SyncAuthError,
    SyncForbiddenError,
    SyncUnavailableError,
)
from core.routing.api.serializers import (
    ChangesResponseSerializer,
    DigestResponseSerializer,
    ErrorEnvelopeSerializer,
    SnapshotResponseSerializer,
    SyncInfoResponseSerializer,
)
from core.routing.application.publish import (
    register_listener,
    unregister_listener,
)
from core.routing.queries import (
    ChangesDelta,
    ChangesReset,
    get_stream_changes,
    get_stream_digest,
    get_stream_info,
    get_stream_snapshot,
)

logger = logging.getLogger(__name__)


class MethodNotAllowedError(APIException):
    status_code = status.HTTP_405_METHOD_NOT_ALLOWED
    default_code = "method_not_allowed"
    default_detail = "Method not allowed."


class InvalidRequestError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "invalid_request"
    default_detail = "A request body was sent."


class BaseSyncAPIView(APIView):
    """Base class for all internal GET-only routing sync endpoints."""

    authentication_classes = [RoutingSyncAuthentication]
    permission_classes = [IsRoutingSyncAuthenticated]
    throttle_classes = []
    http_method_names = ["get", "head"]

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        req_id = get_request_id(request)
        setattr(request, "request_id", req_id)
        return super().dispatch(request, *args, **kwargs)

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        # GET-1: Reject non-GET methods
        method = getattr(request, "method", "").upper()
        if method not in ("GET", "HEAD"):
            raise MethodNotAllowedError("Method not allowed.")

        # GET-4: Reject requests with body
        content_length = request.META.get("CONTENT_LENGTH")
        if (content_length and int(content_length) > 0) or getattr(request, "body", b""):
            raise InvalidRequestError("A request body was sent.")

    def handle_exception(self, exc: Exception) -> Response:
        req_id = getattr(self.request, "request_id", get_request_id(self.request))
        if isinstance(exc, MethodNotAllowedError):
            return self.error_response(
                status.HTTP_405_METHOD_NOT_ALLOWED,
                code="method_not_allowed",
                message=str(getattr(exc, "detail", "Method not allowed.")),
                request_id=req_id,
                headers={"Allow": "GET"},
            )
        if isinstance(exc, InvalidRequestError):
            return self.error_response(
                status.HTTP_400_BAD_REQUEST,
                code="invalid_request",
                message=str(getattr(exc, "detail", "A request body was sent.")),
                request_id=req_id,
            )
        if isinstance(exc, (SyncAuthError, NotAuthenticated, AuthenticationFailed)):
            return self.error_response(
                status.HTTP_401_UNAUTHORIZED,
                code="unauthorized",
                message=str(getattr(exc, "detail", "Missing or invalid bearer token.")),
                request_id=req_id,
                headers={"WWW-Authenticate": "Bearer"},
            )
        if isinstance(exc, (SyncForbiddenError, PermissionDenied)):
            return self.error_response(
                status.HTTP_403_FORBIDDEN,
                code="forbidden",
                message=str(getattr(exc, "detail", "Authenticated caller lacks the sync-read scope.")),
                request_id=req_id,
            )
        if isinstance(exc, SyncUnavailableError):
            return self.error_response(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                code="unavailable",
                message=str(getattr(exc, "detail", "Identity provider is temporarily unavailable.")),
                request_id=req_id,
            )
        return super().handle_exception(exc)

    def finalize_response(self, request: Any, response: Any, *args: Any, **kwargs: Any) -> Response:
        response = super().finalize_response(request, response, *args, **kwargs)
        req_id = getattr(request, "request_id", None) or get_request_id(request)
        response["Content-Type"] = "application/json"
        response["Cache-Control"] = "no-store"
        response[REQUEST_ID_HEADER] = req_id
        if response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
            response["Allow"] = "GET"
        return response

    def error_response(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: list[dict[str, Any]] | None = None,
        request_id: str,
        headers: dict[str, str] | None = None,
    ) -> Response:
        resp_headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            REQUEST_ID_HEADER: request_id,
        }
        if headers:
            resp_headers.update(headers)
        return Response(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "details": details if details is not None else [],
                    "request_id": request_id,
                }
            },
            status=status_code,
            headers=resp_headers,
        )

    def validate_entity(self, entity: str, request_id: str) -> Response | None:
        """Validate stream entity name against enabled entities."""
        enabled = getattr(settings, "ROUTING_SYNC_ENABLED_ENTITIES", ("users", "agents"))
        if entity not in enabled:
            return self.error_response(
                status.HTTP_404_NOT_FOUND,
                code="entity_not_supported",
                message="Entity not enabled or not ready.",
                request_id=request_id,
            )
        return None

    def validate_query(
        self,
        request: Request,
        allowed_params: set[str],
        request_id: str,
    ) -> Response | None:
        """Enforce strict query allowlist per section 8.1."""
        unknown = sorted(set(request.GET.keys()) - allowed_params)
        if unknown:
            return self.error_response(
                status.HTTP_400_BAD_REQUEST,
                code="invalid_query",
                message=f"Unknown query parameter: {unknown[0]}",
                details=[{"field": field, "message": "Unknown query parameter."} for field in unknown],
                request_id=request_id,
            )

        for param in allowed_params:
            values = request.GET.getlist(param)
            if len(values) > 1:
                return self.error_response(
                    status.HTTP_400_BAD_REQUEST,
                    code="invalid_query",
                    message=f"Parameter '{param}' cannot be repeated.",
                    details=[{"field": param, "message": "Parameter cannot be repeated."}],
                    request_id=request_id,
                )
            if len(values) == 1 and values[0].strip() == "":
                return self.error_response(
                    status.HTTP_400_BAD_REQUEST,
                    code="invalid_query",
                    message=f"Parameter '{param}' cannot be empty.",
                    details=[{"field": param, "message": "Parameter cannot be empty."}],
                    request_id=request_id,
                )
        return None


class SyncInfoView(BaseSyncAPIView):
    """GET /internal/info - stream advertisement and server metadata."""

    @extend_schema(
        operation_id="get_internal_info",
        summary="Discover backend identity, streams, versions and limits",
        responses={
            200: OpenApiResponse(response=SyncInfoResponseSerializer, description="Backend sync metadata and available streams"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Invalid query or body sent"),
            401: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unauthorized"),
            403: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Forbidden"),
            405: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Method not allowed"),
            503: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Service unavailable"),
        },
        tags=["Routing Sync"],
    )
    def get(self, request: Request) -> Response:
        req_id = getattr(request, "request_id", get_request_id(request))
        query_err = self.validate_query(request, set(), req_id)
        if query_err is not None:
            return query_err

        backend_id = getattr(settings, "BACKEND_ID", "dept_a")
        enabled = getattr(settings, "ROUTING_SYNC_ENABLED_ENTITIES", ("users", "agents"))
        limits = {
            "snapshot_max_limit": getattr(settings, "ROUTING_SYNC_SNAPSHOT_MAX_LIMIT", 5000),
            "changes_max_limit": getattr(settings, "ROUTING_SYNC_CHANGES_MAX_LIMIT", 2000),
            "longpoll_max_wait_s": getattr(settings, "ROUTING_SYNC_LONGPOLL_MAX_WAIT_S", 30),
        }
        info = get_stream_info(backend_id, enabled, limits)
        return Response({"data": info}, status=status.HTTP_200_OK)


class SyncSnapshotView(BaseSyncAPIView):
    """GET /internal/snapshot/{entity} - keyset-paginated live stream snapshot."""

    @extend_schema(
        operation_id="get_internal_snapshot",
        summary="Keyset-paginated consistent snapshot of live claims",
        parameters=[
            OpenApiParameter("entity", str, OpenApiParameter.PATH, description="Stream entity type (users, agents)"),
            OpenApiParameter("limit", int, OpenApiParameter.QUERY, required=False, description="Page limit (1..5000)"),
            OpenApiParameter("after", str, OpenApiParameter.QUERY, required=False, description="Keyset pagination cursor"),
        ],
        responses={
            200: OpenApiResponse(response=SnapshotResponseSerializer, description="Snapshot page of live claims"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Invalid query or body sent"),
            401: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unauthorized"),
            403: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Forbidden"),
            404: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Entity not supported"),
            405: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Method not allowed"),
            503: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Service unavailable"),
        },
        tags=["Routing Sync"],
    )
    def get(self, request: Request, entity: str) -> Response:
        req_id = getattr(request, "request_id", get_request_id(request))
        entity_err = self.validate_entity(entity, req_id)
        if entity_err is not None:
            return entity_err

        query_err = self.validate_query(request, {"limit", "after"}, req_id)
        if query_err is not None:
            return query_err

        limit_raw = request.GET.get("limit")
        limit = 1000
        max_limit = getattr(settings, "ROUTING_SYNC_SNAPSHOT_MAX_LIMIT", 5000)
        if limit_raw is not None:
            try:
                limit = int(limit_raw)
                if limit < 1 or limit > max_limit:
                    raise ValueError
            except ValueError:
                return self.error_response(
                    status.HTTP_400_BAD_REQUEST,
                    code="invalid_query",
                    message=f"limit must be an integer between 1 and {max_limit}.",
                    details=[{"field": "limit", "message": f"Must be an integer between 1 and {max_limit}."}],
                    request_id=req_id,
                )

        after = request.GET.get("after")
        backend_id = getattr(settings, "BACKEND_ID", "dept_a")
        head_ver, epoch, items, next_after = get_stream_snapshot(entity, after=after, limit=limit)

        data = {
            "backend_id": backend_id,
            "entity_type": entity,
            "epoch": str(epoch),
            "head_version": head_ver,
            "items": items,
            "next_after": next_after,
        }
        return Response({"data": data}, status=status.HTTP_200_OK)


def _is_idle(result: ChangesDelta | ChangesReset, since: int) -> bool:
    return isinstance(result, ChangesDelta) and not result.changes and result.head_version == since


async def _long_poll_changes(
    entity: str,
    *,
    since: int,
    epoch: uuid.UUID,
    limit: int,
    wait: int,
) -> ChangesDelta | ChangesReset:
    """Return changes, holding an idle request for up to ``wait`` seconds without blocking a thread.

    Each read is a short call on Django's sync thread; the wait itself is an ``await`` on the event
    loop. A waiter subscribes before re-reading the head (PUB-5: a wake-up cannot fall between the
    check and the subscription) and re-reads every ``ROUTING_SYNC_LONGPOLL_POLL_INTERVAL_S`` so
    commits made by other processes, which cannot reach this process's listeners, are seen within
    that interval. In-process commits wake the waiter immediately.
    """
    read = sync_to_async(get_stream_changes)
    result = await read(entity, since=since, requested_epoch=epoch, limit=limit)
    if wait <= 0 or not _is_idle(result, since):
        return result

    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait
    interval = float(getattr(settings, "ROUTING_SYNC_LONGPOLL_POLL_INTERVAL_S", 1.0))
    event = asyncio.Event()
    register_listener(entity, event)
    try:
        while True:
            result = await read(entity, since=since, requested_epoch=epoch, limit=limit)
            remaining = deadline - loop.time()
            if not _is_idle(result, since) or remaining <= 0:
                return result
            event.clear()
            try:
                await asyncio.wait_for(event.wait(), timeout=min(interval, remaining))
            except TimeoutError:
                pass
    finally:
        unregister_listener(entity, event)


class SyncChangesView(BaseSyncAPIView):
    """GET /internal/changes/{entity} - bounded changes with optional long-poll.

    The handler is async: a held long-poll must not occupy Django's shared sync thread (spec 8.8).
    """

    @extend_schema(
        operation_id="get_internal_changes",
        summary="Compact change log delta with optional long-poll",
        parameters=[
            OpenApiParameter("entity", str, OpenApiParameter.PATH, description="Stream entity type (users, agents)"),
            OpenApiParameter("since", int, OpenApiParameter.QUERY, required=True, description="Last seen version cursor"),
            OpenApiParameter("epoch", uuid.UUID, OpenApiParameter.QUERY, required=True, description="Held epoch UUID"),
            OpenApiParameter("limit", int, OpenApiParameter.QUERY, required=False, description="Max winners per page (1..2000)"),
            OpenApiParameter("wait", int, OpenApiParameter.QUERY, required=False, description="Long-poll timeout in seconds (0..30)"),
        ],
        responses={
            200: OpenApiResponse(response=ChangesResponseSerializer, description="Change delta or reset signal"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Invalid query or body sent"),
            401: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unauthorized"),
            403: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Forbidden"),
            404: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Entity not supported"),
            405: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Method not allowed"),
            503: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Service unavailable"),
        },
        tags=["Routing Sync"],
    )
    async def get(self, request: Request, entity: str) -> Response:
        req_id = getattr(request, "request_id", get_request_id(request))
        entity_err = self.validate_entity(entity, req_id)
        if entity_err is not None:
            return entity_err

        query_err = self.validate_query(request, {"since", "epoch", "limit", "wait"}, req_id)
        if query_err is not None:
            return query_err

        since_raw = request.GET.get("since")
        if since_raw is None:
            return self.error_response(
                status.HTTP_400_BAD_REQUEST,
                code="invalid_query",
                message="Parameter 'since' is required.",
                details=[{"field": "since", "message": "Required query parameter."}],
                request_id=req_id,
            )
        try:
            since = int(since_raw)
            if since < 0:
                raise ValueError
        except ValueError:
            return self.error_response(
                status.HTTP_400_BAD_REQUEST,
                code="invalid_query",
                message="Parameter 'since' must be an integer >= 0.",
                details=[{"field": "since", "message": "Must be an integer >= 0."}],
                request_id=req_id,
            )

        epoch_raw = request.GET.get("epoch")
        if epoch_raw is None:
            return self.error_response(
                status.HTTP_400_BAD_REQUEST,
                code="invalid_query",
                message="Parameter 'epoch' is required.",
                details=[{"field": "epoch", "message": "Required query parameter."}],
                request_id=req_id,
            )
        try:
            req_epoch = uuid.UUID(epoch_raw)
        except (ValueError, TypeError):
            return self.error_response(
                status.HTTP_400_BAD_REQUEST,
                code="invalid_query",
                message="Parameter 'epoch' must be a canonical UUID string.",
                details=[{"field": "epoch", "message": "Must be a valid UUID string."}],
                request_id=req_id,
            )

        limit_raw = request.GET.get("limit")
        limit = 500
        max_limit = getattr(settings, "ROUTING_SYNC_CHANGES_MAX_LIMIT", 2000)
        if limit_raw is not None:
            try:
                limit = int(limit_raw)
                if limit < 1 or limit > max_limit:
                    raise ValueError
            except ValueError:
                return self.error_response(
                    status.HTTP_400_BAD_REQUEST,
                    code="invalid_query",
                    message=f"limit must be an integer between 1 and {max_limit}.",
                    details=[{"field": "limit", "message": f"Must be an integer between 1 and {max_limit}."}],
                    request_id=req_id,
                )

        wait_raw = request.GET.get("wait")
        wait = 0
        max_wait = getattr(settings, "ROUTING_SYNC_LONGPOLL_MAX_WAIT_S", 30)
        if wait_raw is not None:
            try:
                wait = int(wait_raw)
                if wait < 0 or wait > max_wait:
                    raise ValueError
            except ValueError:
                return self.error_response(
                    status.HTTP_400_BAD_REQUEST,
                    code="invalid_query",
                    message=f"wait must be an integer between 0 and {max_wait}.",
                    details=[{"field": "wait", "message": f"Must be an integer between 0 and {max_wait}."}],
                    request_id=req_id,
                )

        result = await _long_poll_changes(entity, since=since, epoch=req_epoch, limit=limit, wait=wait)

        backend_id = getattr(settings, "BACKEND_ID", "dept_a")
        if isinstance(result, ChangesReset):
            return Response(
                {
                    "data": {
                        "backend_id": backend_id,
                        "entity_type": entity,
                        "epoch": str(result.epoch),
                        "mode": "reset",
                        "reason": result.reason,
                        "head_version": result.head_version,
                    }
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "data": {
                    "backend_id": backend_id,
                    "entity_type": entity,
                    "epoch": str(result.epoch),
                    "mode": "delta",
                    "version": result.version,
                    "head_version": result.head_version,
                    "has_more": result.has_more,
                    "oldest_retained_version": result.oldest_retained_version,
                    "changes": result.changes,
                }
            },
            status=status.HTTP_200_OK,
        )


class SyncDigestView(BaseSyncAPIView):
    """GET /internal/digest/{entity} - drift check digest."""

    @extend_schema(
        operation_id="get_internal_digest",
        summary="Live claims checksum and row count",
        parameters=[
            OpenApiParameter("entity", str, OpenApiParameter.PATH, description="Stream entity type (users, agents)"),
        ],
        responses={
            200: OpenApiResponse(response=DigestResponseSerializer, description="Live stream digest and version"),
            400: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Invalid query or body sent"),
            401: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Unauthorized"),
            403: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Forbidden"),
            404: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Entity not supported"),
            405: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Method not allowed"),
            503: OpenApiResponse(response=ErrorEnvelopeSerializer, description="Service unavailable"),
        },
        tags=["Routing Sync"],
    )
    def get(self, request: Request, entity: str) -> Response:
        req_id = getattr(request, "request_id", get_request_id(request))
        entity_err = self.validate_entity(entity, req_id)
        if entity_err is not None:
            return entity_err

        query_err = self.validate_query(request, set(), req_id)
        if query_err is not None:
            return query_err

        count, checksum, version, epoch = get_stream_digest(entity)
        data = {
            "entity_type": entity,
            "epoch": str(epoch),
            "version": version,
            "count": count,
            "checksum": checksum,
        }
        return Response({"data": data}, status=status.HTTP_200_OK)
