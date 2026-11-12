"""REST API: list + create notifications (hybrid reliability fallback)."""

from django.db.models import Q
from django.utils import timezone
from drf_api_contracts import ResponseContract, ResponseSchemaFactory
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_serializer, extend_schema_view
from rest_framework import generics
from rest_framework.exceptions import ErrorDetail

from core.common.api.correlation import get_request_id
from core.common.api.pagination import ResultsSetPagination
from core.websocket.models import Notification

from .serializer import NotificationSerializer


@extend_schema_view(
    get=extend_schema(
        tags=["Websocket Notifications"],
        parameters=[
            OpenApiParameter(
                "page",
                {"type": "integer", "minimum": 1},
                OpenApiParameter.QUERY,
                required=False,
                description="A page number within the paginated result set.",
            ),
            OpenApiParameter(
                "page_size",
                {"type": "integer", "minimum": 1, "maximum": 100},
                OpenApiParameter.QUERY,
                required=False,
                description="Number of results to return per page.",
            ),
            OpenApiParameter(
                "since",
                {"type": "integer", "minimum": 0},
                OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Reconnection cursor: return only notifications whose id is greater than this value. "
                    "Pass the highest id already received."
                ),
            ),
            OpenApiParameter(
                "user_id",
                {"type": "integer", "minimum": 0},
                OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Return only notifications targeted at this user; broadcasts are excluded. Only the caller's "
                    "own id is honoured: any other id returns an empty page."
                ),
            ),
        ],
        responses={
            200: extend_schema_serializer(many=False)(
                ResponseSchemaFactory.paginated("Notification", NotificationSerializer)
            ),
            400: ResponseContract.problem(400).schema,
            404: ResponseContract.problem(404).schema,
        },
        description=(
            "List visible, unexpired notifications in data with meta.pagination "
            "(count, page, page_size, next, previous). Page size defaults to 25 and is limited to 100. "
            "An invalid page_size returns 400; a nonexistent or invalid page returns 404. "
            "An unknown or repeated query parameter, or a since / user_id that is not a non-negative "
            "integer, returns 400 invalid_query."
        ),
    ),
    post=extend_schema(
        tags=["Websocket Notifications"],
        responses={
            201: ResponseContract.created("Notification", NotificationSerializer).schema,
            401: ResponseContract.unauthorized().schema,
        },
    ),
)
class NotificationListCreateView(generics.ListCreateAPIView):
    """List unread notifications or publish a real-time event notification."""
    serializer_class = NotificationSerializer
    pagination_class = ResultsSetPagination

    def list(self, request, *args, **kwargs):
        error = _query_error(request)
        if error is not None:
            return error
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        response.data = {"data": response.data}
        return response

    def get_queryset(self):
        qs = Notification.objects.filter(expiry_date__gte=timezone.now()).filter(
            Q(target_user__isnull=True) | Q(target_user=self.request.user)
        )
        # Support ?since=<id> for reconnecting clients (hybrid reliability)
        since = self.request.query_params.get("since")
        if since is not None:
            qs = qs.filter(pk__gt=int(since))
        # Support ?user_id=<id> for per-user filtering — only allow own ID (IDOR guard)
        user_id = self.request.query_params.get("user_id")
        if user_id is not None:
            if int(user_id) != self.request.user.pk:
                return qs.none()
            qs = qs.filter(target_user_id=int(user_id))
        return qs


QUERY_PARAMS = frozenset({"page", "page_size", "since", "user_id"})
ID_PARAMS = ("since", "user_id")
MAX_ID = 2**63 - 1  # BigAutoField upper bound


def _query_error(request):
    """Reject unknown, repeated or malformed list parameters (QRY-1, QRY-2, QRY-3).

    page / page_size keep the paginator's own validation (400 for page_size, 404 for page).
    """
    errors = {}
    for key in request.query_params:
        if key not in QUERY_PARAMS:
            errors[key] = [ErrorDetail("Unknown query parameter.", code="invalid_query")]
        elif len(request.query_params.getlist(key)) > 1:
            errors[key] = [ErrorDetail("This parameter must not be repeated.", code="invalid_query")]
    for key in ID_PARAMS:
        raw = request.query_params.get(key)
        if raw is None or key in errors:
            continue
        if not (raw.isascii() and raw.isdecimal() and len(raw) <= len(str(MAX_ID)) and int(raw) <= MAX_ID):
            errors[key] = [ErrorDetail("Enter a non-negative integer.", code="invalid_query")]
    if not errors:
        return None
    return ResponseContract.bad_request().respond_problem(
        code="invalid_query", errors=errors, request_id=get_request_id(request)
    )
