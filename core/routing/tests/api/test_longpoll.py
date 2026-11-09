"""Long-poll behaviour of GET /internal/changes/{entity} under the async handler."""

import asyncio
import time
import uuid

import pytest
from asgiref.sync import sync_to_async
from django.db import transaction
from django.test import AsyncClient

from core.routing.application import publish
from core.routing.models import SyncState

VALID_STATIC_TOKEN = "test-sync-token-256bits-long-valid-base64url"
AUTH = {"headers": {"Authorization": f"Bearer {VALID_STATIC_TOKEN}"}}
AGENT_KEY = "bbbbbbbb-1111-4000-8000-000000000001"

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def stream_epoch():
    epoch = uuid.uuid4()
    SyncState.objects.create(entity_type="agents", version=0, epoch=epoch)
    return epoch


def _changes_url(epoch: uuid.UUID, wait: int) -> str:
    return f"/internal/changes/agents?since=0&epoch={epoch}&wait={wait}"


def _publish_agent_upsert() -> None:
    with transaction.atomic():
        publish._publish(publish._change("agents", AGENT_KEY, "upsert"))


async def test_idle_long_poll_returns_empty_delta_at_deadline(settings, stream_epoch):
    settings.ROUTING_SYNC_LONGPOLL_POLL_INTERVAL_S = 0.2
    started = time.monotonic()

    response = await AsyncClient().get(_changes_url(stream_epoch, wait=1), **AUTH)

    elapsed = time.monotonic() - started
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["mode"] == "delta"
    assert body["changes"] == []
    assert body["version"] == 0
    assert 0.9 <= elapsed < 3


async def test_held_long_poll_does_not_block_other_sync_requests(settings, stream_epoch):
    settings.ROUTING_SYNC_LONGPOLL_POLL_INTERVAL_S = 0.5
    client = AsyncClient()

    held = asyncio.create_task(client.get(_changes_url(stream_epoch, wait=3), **AUTH))
    await asyncio.sleep(0.3)
    started = time.monotonic()
    info = await client.get("/internal/info", **AUTH)
    info_elapsed = time.monotonic() - started

    assert info.status_code == 200
    assert info_elapsed < 1.5, "a held long-poll blocked an unrelated sync request"
    assert not held.done()
    await held


async def test_in_process_publish_wakes_waiter_before_poll_interval(settings, stream_epoch):
    settings.ROUTING_SYNC_LONGPOLL_POLL_INTERVAL_S = 10
    held = asyncio.create_task(AsyncClient().get(_changes_url(stream_epoch, wait=8), **AUTH))
    await asyncio.sleep(0.3)
    started = time.monotonic()

    await sync_to_async(_publish_agent_upsert)()
    response = await held

    assert time.monotonic() - started < 3
    body = response.json()["data"]
    assert body["version"] == 1
    assert [change["key"] for change in body["changes"]] == [AGENT_KEY]


async def test_commit_from_another_process_is_seen_at_next_poll(settings, stream_epoch, monkeypatch):
    settings.ROUTING_SYNC_LONGPOLL_POLL_INTERVAL_S = 0.3
    # Simulate a writer in another process: its in-memory wake-up never reaches this process.
    monkeypatch.setattr(publish, "notify_listeners", lambda entity_type: None)
    held = asyncio.create_task(AsyncClient().get(_changes_url(stream_epoch, wait=8), **AUTH))
    await asyncio.sleep(0.3)
    started = time.monotonic()

    await sync_to_async(_publish_agent_upsert)()
    response = await held

    assert time.monotonic() - started < 2
    assert response.json()["data"]["version"] == 1
