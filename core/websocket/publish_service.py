"""
Sync-safe publish utility for pushing updates to WS clients.

Callable from sync Django code (views, services, Celery tasks)
without requiring an async context.
"""

import json
import logging

import redis
from django.conf import settings

logger = logging.getLogger(__name__)

_sync_redis: redis.Redis | None = None


def _get_sync_redis() -> redis.Redis:
    """Lazy-init sync Redis client."""
    global _sync_redis
    if _sync_redis is None:
        _sync_redis = redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)
    return _sync_redis


def _publish(channel: str, data: dict) -> None:
    """Publish JSON payload to Redis channel. Logs errors, never raises."""
    try:
        _get_sync_redis().publish(channel, json.dumps(data))
    except Exception:
        logger.error("Failed to publish to Redis channel %s", channel, exc_info=True)


def publish_equipment_update(
    bench_id: int,
    equipment_id: int,
    equipment_type: str,
    status: str,
) -> None:
    """Publish equipment status change to WS clients watching a lab."""
    from django.utils import timezone

    _publish(
        f"ws:equipment:{bench_id}",
        {
            "type": "equipment_status",
            "bench_id": bench_id,
            "equipment_id": equipment_id,
            "equipment_type": equipment_type,
            "status": status,
            "timestamp": timezone.now().isoformat(),
        },
    )


def publish_monitoring_update(
    bench_id: int,
    event_type: str,
    data: dict,
) -> None:
    """Publish monitoring data update to WS clients watching a lab."""
    from django.utils import timezone

    _publish(
        f"ws:monitoring:{bench_id}",
        {
            "type": "monitoring_update",
            "bench_id": bench_id,
            "event_type": event_type,
            "data": data,
            "timestamp": timezone.now().isoformat(),
        },
    )


def publish_computing_activity_update(computing_id: int, data: dict) -> None:
    """Publish a computing activity status change to WS clients watching one computer."""
    from django.utils import timezone

    _publish(
        f"ws:computing:{computing_id}",
        {
            "type": "computing_activity",
            "computer_id": computing_id,
            "event_type": "computer_status_change",
            "data": data,
            "timestamp": timezone.now().isoformat(),
        },
    )


def publish_dashboard_status_update(event_type: str, data: dict) -> None:
    """Broadcast monitoring updates for all-labs dashboard."""
    from django.utils import timezone

    _publish(
        "ws:monitoring:dashboard",
        {
            "type": "monitoring_update",
            "event_type": event_type,
            "data": data,
            "timestamp": timezone.now().isoformat(),
        },
    )


def serialize_notification_payload(
    notification,
    *,
    event: str = "created",
    is_read: bool = False,
    replay: bool = False,
) -> dict:
    """Build the canonical WebSocket payload for a Notification row."""
    return {
        "type": "notification",
        "event": event,
        "id": notification.pk,
        "message": notification.message,
        "details": notification.details or "",
        "message_type": notification.message_type,
        "display_mode": notification.display_mode,
        "is_dismissible": notification.is_dismissible,
        "expiry_date": notification.expiry_date.isoformat() if notification.expiry_date else None,
        "action_path": notification.action_path,
        "is_read": bool(is_read),
        "replay": bool(replay),
        "created": notification.created.isoformat(),
    }


def publish_notification_record(notification, *, event: str = "created") -> None:
    """Publish a persisted Notification to either its target user channel or broadcast."""
    payload = serialize_notification_payload(notification, event=event, is_read=False, replay=False)
    if notification.target_user_id:
        _publish(f"ws:notifications:user:{notification.target_user_id}", payload)
    else:
        _publish("ws:notifications:broadcast", payload)


def publish_notification_removed(
    notification_id: int,
    *,
    display_mode: str = "banner",
    target_user_id: int | None = None,
) -> None:
    """Notify connected clients to remove an expired or deleted notification (e.g. an active banner)."""
    payload = {
        "type": "notification",
        "event": "removed",
        "id": notification_id,
        "display_mode": display_mode,
    }
    if target_user_id:
        _publish(f"ws:notifications:user:{target_user_id}", payload)
    else:
        _publish("ws:notifications:broadcast", payload)


def publish_notification(
    message: str,
    message_type: str = "info",
    details: str = "",
    notification_id: int | None = None,
    target_user_id: int | None = None,
    *,
    display_mode: str = "alert",
    is_dismissible: bool = True,
    expiry_date: str | None = None,
    action_path: str = "",
) -> None:
    """Publish notification to WS clients (per-user if targeted, otherwise broadcast)."""
    from django.utils import timezone

    payload = {
        "type": "notification",
        "event": "created",
        "id": notification_id,
        "message": message,
        "details": details,
        "message_type": message_type,
        "display_mode": display_mode,
        "is_dismissible": is_dismissible,
        "expiry_date": expiry_date,
        "action_path": action_path,
        "is_read": False,
        "replay": False,
        "created": timezone.now().isoformat(),
    }
    if target_user_id:
        _publish(f"ws:notifications:user:{target_user_id}", payload)
    else:
        _publish("ws:notifications:broadcast", payload)


def publish_user_notification(
    target_user_id: int,
    message: str,
    message_type: str = "info",
    details: str = "",
    notification_id: int | None = None,
    action_path: str = "",
    *,
    display_mode: str = "alert",
    is_dismissible: bool = True,
    expiry_date: str | None = None,
) -> None:
    """Publish a notification to one user's channel only (never broadcast)."""
    from django.utils import timezone

    _publish(
        f"ws:notifications:user:{target_user_id}",
        {
            "type": "notification",
            "event": "created",
            "id": notification_id,
            "message": message,
            "details": details,
            "message_type": message_type,
            "display_mode": display_mode,
            "is_dismissible": is_dismissible,
            "expiry_date": expiry_date,
            "action_path": action_path,
            "is_read": False,
            "replay": False,
            "created": timezone.now().isoformat(),
        },
    )


def publish_task_progress(
    task_id: str,
    progress: int,
    message: str = "",
) -> None:
    """Publish intermediate progress from within a Celery task."""
    from django.utils import timezone

    _publish(
        f"ws:tasks:{task_id}",
        {
            "type": "task_progress",
            "task_id": task_id,
            "progress": progress,
            "message": message,
            "timestamp": timezone.now().isoformat(),
        },
    )
