"""REST API: list + create notifications (hybrid reliability fallback)."""

from django.db.models import Q
from django.utils import timezone
from drf_api_contracts import ResponseContract, ResponseSchemaFactory
from drf_spectacular.utils import extend_schema, extend_schema_serializer, extend_schema_view
from rest_framework import generics

from core.common.api.pagination import ResultsSetPagination
from core.websocket.models import Notification

from .serializer import NotificationSerializer


@extend_schema_view(
    get=extend_schema(
        tags=["Websocket Notifications"],
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
            "An invalid page_size returns 400; a nonexistent or invalid page returns 404."
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
        if since and since.isdigit():
            qs = qs.filter(pk__gt=int(since))
        # Support ?user_id=<id> for per-user filtering — only allow own ID (IDOR guard)
        user_id = self.request.query_params.get("user_id")
        if user_id and user_id.isdigit():
            if int(user_id) != self.request.user.pk:
                return qs.none()
            qs = qs.filter(target_user_id=int(user_id))
        return qs
