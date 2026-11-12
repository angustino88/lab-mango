"""Idempotent audit recording by UID (Idempotency-Key, RW-6)."""

import threading
import uuid

import pytest
from django.db import connection
from rest_framework.test import APIClient

from core.labs.features.resource_audit.public import (
    IdempotencyKeyReuseError,
    InvalidIdempotencyKeyError,
    RecordAuditByUidInput,
    record_audit_by_uid_once,
)
from core.labs.models.auditing.resource_audit import ResourceAudit
from tests.factories import BenchFactory, LabComputerFactory, UserFactory, grant_labs_role


@pytest.fixture
def coordinator(db):
    user = UserFactory(username="idem_coord", email="idem_coord@example.com")
    grant_labs_role(user, "coord")
    return user


@pytest.fixture
def client(coordinator):
    api = APIClient()
    api.force_authenticate(user=coordinator)
    return api


def _post(client, uid, body, key=None):
    headers = {"HTTP_IDEMPOTENCY_KEY": key} if key is not None else {}
    return client.post(f"/api/labs/resources/uid/{uid}/audits", body, format="json", **headers)


@pytest.mark.django_db
class TestIdempotentRecordApi:
    def test_first_request_creates_and_repeat_replays(self, client):
        bench = BenchFactory(sku="IDEM-BENCH-01")
        key = str(uuid.uuid4())
        body = {"result": "PASS", "remarks": "Checked", "audited_at": "2026-11-12T09:30:00Z"}

        first = _post(client, bench.uid, body, key)
        second = _post(client, bench.uid, body, key)

        assert first.status_code == 201
        assert "Idempotency-Replayed" not in first
        assert second.status_code == 201
        assert second["Idempotency-Replayed"] == "true"
        assert second.json()["data"]["id"] == first.json()["data"]["id"]
        assert ResourceAudit.objects.filter(idempotency_key=key).count() == 1

    def test_same_key_different_body_is_refused(self, client):
        bench = BenchFactory(sku="IDEM-BENCH-02")
        key = str(uuid.uuid4())
        assert _post(client, bench.uid, {"result": "PASS"}, key).status_code == 201

        response = _post(client, bench.uid, {"result": "FAIL"}, key)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "idempotency_key_reuse"
        assert ResourceAudit.objects.filter(idempotency_key=key).count() == 1

    def test_same_key_other_resource_is_refused(self, client):
        first, other = BenchFactory(sku="IDEM-BENCH-03"), LabComputerFactory(sku="IDEM-COMP-03")
        key = str(uuid.uuid4())
        assert _post(client, first.uid, {"result": "PASS"}, key).status_code == 201

        assert _post(client, other.uid, {"result": "PASS"}, key).status_code == 422

    def test_key_is_scoped_to_the_auditor(self, client):
        bench = BenchFactory(sku="IDEM-BENCH-04")
        key = str(uuid.uuid4())
        other_user = grant_labs_role(UserFactory(username="idem_other", email="idem_other@example.com"), "coord")
        other_client = APIClient()
        other_client.force_authenticate(user=other_user)

        assert _post(client, bench.uid, {"result": "PASS"}, key).status_code == 201
        assert _post(other_client, bench.uid, {"result": "PASS"}, key).status_code == 201
        assert ResourceAudit.objects.filter(idempotency_key=key).count() == 2

    @pytest.mark.parametrize("key", ["", "   ", "k" * 129])
    def test_invalid_key_is_rejected(self, client, key):
        bench = BenchFactory(sku=f"IDEM-BENCH-BAD-{len(key)}")

        response = _post(client, bench.uid, {"result": "PASS"}, key)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_idempotency_key"
        assert not ResourceAudit.objects.exists()

    def test_without_key_each_request_creates_an_audit(self, client):
        bench = BenchFactory(sku="IDEM-BENCH-05")

        assert _post(client, bench.uid, {"result": "PASS"}).status_code == 201
        assert _post(client, bench.uid, {"result": "PASS"}).status_code == 201

        assert ResourceAudit.objects.filter(idempotency_key__isnull=True).count() == 2


@pytest.mark.django_db
def test_command_rejects_reuse_and_bad_key(coordinator):
    bench = BenchFactory(sku="IDEM-BENCH-06")
    command = RecordAuditByUidInput(uid=bench.uid, result="PASS")
    record_audit_by_uid_once(command, actor=coordinator, idempotency_key="key-1")

    with pytest.raises(IdempotencyKeyReuseError):
        record_audit_by_uid_once(
            RecordAuditByUidInput(uid=bench.uid, result="NOK"), actor=coordinator, idempotency_key="key-1"
        )
    with pytest.raises(InvalidIdempotencyKeyError):
        record_audit_by_uid_once(command, actor=coordinator, idempotency_key="")


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_with_same_key_create_one_audit():
    user = grant_labs_role(UserFactory(username="idem_race", email="idem_race@example.com"), "coord")
    bench = BenchFactory(sku="IDEM-BENCH-RACE")
    command = RecordAuditByUidInput(uid=bench.uid, result="PASS", remarks="race")
    barrier = threading.Barrier(2)
    results: list[bool] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait(timeout=10)
            results.append(record_audit_by_uid_once(command, actor=user, idempotency_key="race-key").replayed)
        except BaseException as error:  # pragma: no cover - surfaced by the assertion below
            errors.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    assert sorted(results) == [False, True]
    assert ResourceAudit.objects.filter(auditor=user, idempotency_key="race-key").count() == 1
