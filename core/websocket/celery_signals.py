"""
Bridge Celery task lifecycle signals to Redis pub/sub.

Connects to task_prerun, task_postrun, task_failure signals
and publishes state changes to ws:tasks:{task_id} channels.
"""

import json
import logging

from celery.signals import task_failure, task_postrun, task_prerun

logger = logging.getLogger(__name__)


@task_prerun.connect
def on_task_prerun(sender=None, task_id=None, **kwargs) -> None:
    """Task started executing."""
    _publish_state(task_id, "STARTED")


@task_postrun.connect
def on_task_postrun(
    sender=None, task_id=None, retval=None, state=None, **kwargs
) -> None:
    """Task finished (success or other terminal state)."""
    _publish_state(task_id, state or "SUCCESS", result=_safe_serialize(retval))


@task_failure.connect
def on_task_failure(
    sender=None, task_id=None, exception=None, **kwargs
) -> None:
    """Task raised an exception."""
    _publish_state(
        task_id, "FAILURE", result=str(exception) if exception else None
    )


def _publish_state(task_id: str, state: str, result=None) -> None:
    """Publish task state change to Redis."""
    from django.utils import timezone

    from core.websocket.publish_service import _publish

    _publish(
        f"ws:tasks:{task_id}",
        {
            "type": "task_state",
            "task_id": task_id,
            "state": state,
            "result": result,
            "timestamp": timezone.now().isoformat(),
        },
    )


def _safe_serialize(value) -> str | None:
    """Convert task result to JSON-safe value."""
    if value is None:
        return None
    try:
        json.dumps(value)
        return value  # Already JSON-serializable
    except (TypeError, ValueError):
        return str(value)
