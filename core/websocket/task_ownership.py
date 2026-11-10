"""Ownership of Celery tasks whose progress a user may watch on ws/tasks/{task_id}.

The task-progress handler is deny-by-default: it only streams a task to the user
recorded as its owner. Enqueue user-visible tasks with ``enqueue_user_task`` (or call
``register_task_owner`` before publishing) and return the task id to that user.

The owner is written to the shared cache *before* the task is published, so a client
that connects as soon as it receives the id is never refused by a race. Production
uses Redis for the cache, so the web, worker and ASGI processes share the record.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.core.cache import cache

TASK_OWNER_TTL_SECONDS = 24 * 60 * 60


def _key(task_id: str) -> str:
    return f"task_owner:{task_id}"


def register_task_owner(task_id: str, user_id: int, *, ttl: int = TASK_OWNER_TTL_SECONDS) -> None:
    """Record ``user_id`` as the only user allowed to watch ``task_id``."""
    if not task_id or user_id is None:
        raise ValueError("A task id and an owner user id are required.")
    cache.set(_key(str(task_id)), int(user_id), ttl)


def task_owner_id(task_id: str) -> int | None:
    """Return the registered owner of ``task_id``, or None when unknown or expired."""
    return cache.get(_key(str(task_id)))


def is_task_owner(task_id: str, user_id: Any) -> bool:
    owner_id = task_owner_id(task_id)
    return owner_id is not None and user_id is not None and str(owner_id) == str(user_id)


def enqueue_user_task(task: Any, *, actor: Any, args: tuple = (), kwargs: dict | None = None, **options: Any):
    """Publish ``task`` for an authenticated ``actor`` and make them its progress owner.

    Returns the Celery ``AsyncResult``; give ``result.id`` to the client for ws/tasks/{id}.
    """
    if not getattr(actor, "is_authenticated", False):
        raise ValueError("Only an authenticated user can own a watched task.")
    task_id = options.pop("task_id", None) or str(uuid.uuid4())
    register_task_owner(task_id, actor.pk)
    return task.apply_async(args=args, kwargs=kwargs or {}, task_id=task_id, **options)


__all__ = [
    "TASK_OWNER_TTL_SECONDS",
    "enqueue_user_task",
    "is_task_owner",
    "register_task_owner",
    "task_owner_id",
]
