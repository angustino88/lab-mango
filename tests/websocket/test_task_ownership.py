"""Task ownership registration used by the task-progress WebSocket."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.cache import cache

from core.websocket.task_ownership import (
    enqueue_user_task,
    is_task_owner,
    register_task_owner,
    task_owner_id,
)


@pytest.fixture(autouse=True)
def clean_cache():
    cache.clear()
    yield
    cache.clear()


def test_owner_is_registered_before_the_task_is_published():
    actor = SimpleNamespace(pk=42, is_authenticated=True)
    seen_owner = {}

    def apply_async(*, args, kwargs, task_id, **options):
        # A client may connect as soon as the id exists; ownership must already be recorded.
        seen_owner["owner"] = task_owner_id(task_id)
        return SimpleNamespace(id=task_id)

    task = Mock(apply_async=Mock(side_effect=apply_async))

    result = enqueue_user_task(task, actor=actor, args=(1,), kwargs={"x": 2}, queue="exports")

    assert seen_owner["owner"] == 42
    assert is_task_owner(result.id, 42)
    assert not is_task_owner(result.id, 43)
    task.apply_async.assert_called_once_with(args=(1,), kwargs={"x": 2}, task_id=result.id, queue="exports")


def test_explicit_task_id_is_kept():
    actor = SimpleNamespace(pk=5, is_authenticated=True)
    task = Mock(apply_async=Mock(side_effect=lambda **kw: SimpleNamespace(id=kw["task_id"])))

    result = enqueue_user_task(task, actor=actor, task_id="fixed-id")

    assert result.id == "fixed-id"
    assert task_owner_id("fixed-id") == 5


def test_anonymous_actor_cannot_own_a_task():
    task = Mock()
    with pytest.raises(ValueError):
        enqueue_user_task(task, actor=SimpleNamespace(pk=None, is_authenticated=False))
    task.apply_async.assert_not_called()


def test_unknown_task_has_no_owner():
    assert task_owner_id("never-registered") is None
    assert not is_task_owner("never-registered", 1)


def test_register_requires_task_and_owner():
    with pytest.raises(ValueError):
        register_task_owner("", 1)
    with pytest.raises(ValueError):
        register_task_owner("t", None)
