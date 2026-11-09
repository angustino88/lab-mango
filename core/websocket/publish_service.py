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


def publish_notification(
    message: str,
    message_type: str = "info",
    details: str = "",
    notification_id: int | None = None,
    target_user_id: int | None = None,
) -> None:
    """Publish notification to WS clients (broadcast + optional per-user)."""
    from django.utils import timezone

    payload = {
        "type": "notification",
        "id": notification_id,
        "message": message,
        "details": details,
        "message_type": message_type,
        "created": timezone.now().isoformat(),
    }
    _publish("ws:notifications:broadcast", payload)
    if target_user_id:
        _publish(f"ws:notifications:user:{target_user_id}", payload)


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
