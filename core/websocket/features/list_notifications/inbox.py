"""Notification inbox: unread count and read receipts for the header bell.

Race guard: ``notification_read_unique`` (user, notification). Marking read uses ``get_or_create`` /
``bulk_create(ignore_conflicts=True)``, so repeated or concurrent requests are safe.
"""

from drf_api_contracts import ResponseContract
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.common.api.correlation import get_request_id
from core.websocket.models import Notification, NotificationRead

from .api import visible_notifications
from .serializer import NotificationSerializer

MAX_UNREAD_COUNT = 100
MARK_ALL_LIMIT = 500


class UnreadCountSerializer(serializers.Serializer):
    unread_count = serializers.IntegerField(
        help_text=f"Unread, unexpired alert notifications for the caller, capped at {MAX_UNREAD_COUNT}."
    )


class MarkAllReadSerializer(serializers.Serializer):
    marked_count = serializers.IntegerField(help_text="Alert notifications newly marked as read.")


class NotificationUnreadCountView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Websocket Notifications"],
        responses={
            200: ResponseContract.success("NotificationUnreadCount", UnreadCountSerializer).schema,
            401: ResponseContract.unauthorized().schema,
        },
        description=(
            "Number of unread, unexpired one-time alert notifications for the caller (for the header bell). "
            "Expiring banners are excluded from the badge count."
        ),
    )
    def get(self, request):
        count = (
            visible_notifications(request.user)
            .filter(display_mode=Notification.ALERT, is_read=False)[:MAX_UNREAD_COUNT]
            .count()
        )
        return Response({"data": {"unread_count": count}})


class NotificationMarkReadView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Websocket Notifications"],
        request=None,
        responses={
            200: ResponseContract.success("NotificationMarkRead", NotificationSerializer).schema,
            404: ResponseContract.problem(404).schema,
        },
        description="Mark one visible notification (alert or banner dismissal) as read. Repeating is a no-op. Others' notifications return 404.",
    )
    def post(self, request, notification_id: int):
        notification = visible_notifications(request.user).filter(pk=notification_id).first()
        if notification is None:
            return ResponseContract.not_found().respond_problem(code="not_found", request_id=get_request_id(request))
        NotificationRead.objects.get_or_create(user=request.user, notification=notification)
        notification.is_read = True
        return Response({"data": NotificationSerializer(notification).data})


class NotificationMarkAllReadView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Websocket Notifications"],
        request=None,
        responses={
            200: ResponseContract.success("NotificationMarkAllRead", MarkAllReadSerializer).schema,
            401: ResponseContract.unauthorized().schema,
        },
        description=(
            f"Mark the caller's visible unread one-time alert notifications as read (up to {MARK_ALL_LIMIT} per call). "
            "Active banners are not dismissed by this action."
        ),
    )
    def post(self, request):
        ids = list(
            visible_notifications(request.user)
            .filter(display_mode=Notification.ALERT, is_read=False)
            .values_list("pk", flat=True)[:MARK_ALL_LIMIT]
        )
        created = NotificationRead.objects.bulk_create(
            [NotificationRead(user=request.user, notification_id=pk) for pk in ids], ignore_conflicts=True
        )
        return Response({"data": {"marked_count": len(created)}}, status=status.HTTP_200_OK)
