"""Unit tests for core.common.notifications engine and outbox ledger."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from core.common.models.outbox import AbstractOutboxLedger
from core.common.notifications.backoff import calculate_backoff_delay
from core.common.notifications.contracts import (
    DeliveryOutcome,
    DeliveryState,
    NotificationChannel,
    NotificationPayload,
    OutboxLease,
)
from core.common.notifications.dedupe import compute_dedupe_key
from core.common.notifications.lease import (
    claim_leased_record,
    complete_leased_record,
    reap_expired_records,
    verify_lease_ownership,
)


class DummyOutbox(AbstractOutboxLedger):
    """Concrete model subclass for testing abstract outbox ledger definitions."""

    class Meta:
        app_label = "common"
        abstract = True


def test_notification_contracts():
    payload = NotificationPayload(
        channel=NotificationChannel.EMAIL,
        recipient_id=123,
        subject="Test subject",
        text="Test body",
        metadata={"source": "unit_test"},
    )
    assert payload.channel == "email"
    assert payload.recipient_id == 123
    assert payload.metadata["source"] == "unit_test"

    outcome = DeliveryOutcome(state=DeliveryState.SENT.value, code="ok")
    assert outcome.state == "sent"
    assert outcome.code == "ok"

    now = datetime.now(timezone.utc)
    lease = OutboxLease(token=uuid4(), until=now + timedelta(seconds=120))
    assert isinstance(lease.token, UUID)
    assert lease.until > now


def test_backoff_delay_calculation():
    # Attempt 1: 30s base
    assert calculate_backoff_delay(attempt=1, base_seconds=30, jitter=0.0) == timedelta(seconds=30)
    # Attempt 2: 60s base
    assert calculate_backoff_delay(attempt=2, base_seconds=30, jitter=0.0) == timedelta(seconds=60)
    # Attempt 3: 120s base
    assert calculate_backoff_delay(attempt=3, base_seconds=30, jitter=0.0) == timedelta(seconds=120)
    # Jitter clamped [0.0, 1.0]
    delay_with_jitter = calculate_backoff_delay(attempt=1, base_seconds=30, jitter=0.5)
    assert delay_with_jitter == timedelta(seconds=45)
    # Max delay capped
    assert calculate_backoff_delay(attempt=10, base_seconds=30, max_seconds=900, jitter=0.0) == timedelta(seconds=900)


def test_dedupe_key_generation():
    key1 = compute_dedupe_key("booking", 101, "email", "2026-10-23")
    key2 = compute_dedupe_key("booking", 101, "email", "2026-10-23")
    key3 = compute_dedupe_key("booking", 102, "email", "2026-10-23")

    assert key1 == key2
    assert key1 != key3
    assert len(key1) == 64  # SHA-256 hex digest length


def test_verify_lease_ownership():
    now = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
    token = uuid4()

    valid_row = MagicMock()
    valid_row.state = "leased"
    valid_row.lease_token = token
    valid_row.lease_until = now + timedelta(seconds=60)

    assert verify_lease_ownership(valid_row, token=token, now=now) is True

    # Expired lease
    expired_row = MagicMock()
    expired_row.state = "leased"
    expired_row.lease_token = token
    expired_row.lease_until = now - timedelta(seconds=1)
    assert verify_lease_ownership(expired_row, token=token, now=now) is False

    # Different token
    assert verify_lease_ownership(valid_row, token=uuid4(), now=now) is False

    # Token None
    assert verify_lease_ownership(valid_row, token=None, now=now) is False


def test_claim_leased_record_normal_and_exhausted():
    now = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
    mock_qs = MagicMock()

    with patch("core.common.notifications.lease.django_transaction.atomic"):
        # Case 1: Empty queryset returns None
        mock_qs.select_for_update.return_value.filter.return_value.order_by.return_value.first.return_value = None
        claimed = claim_leased_record(mock_qs, now=now)
        assert claimed is None

        # Case 2: Available pending row claimed
        available_row = MagicMock()
        available_row.expires_at = now + timedelta(hours=1)
        available_row.attempts = 1
        mock_qs.select_for_update.return_value.filter.return_value.order_by.return_value.first.return_value = available_row

        claimed = claim_leased_record(mock_qs, now=now)
        assert claimed is available_row
        assert available_row.state == "leased"
        assert available_row.attempts == 2
        assert available_row.lease_token is not None
        assert available_row.lease_until == now + timedelta(seconds=120)
        available_row.save.assert_called_once()

        # Case 3: Exhausted attempts marks failed
        exhausted_row = MagicMock()
        exhausted_row.expires_at = now + timedelta(hours=1)
        exhausted_row.attempts = 5
        mock_qs.select_for_update.return_value.filter.return_value.order_by.return_value.first.return_value = exhausted_row

        claimed = claim_leased_record(mock_qs, now=now)
        assert claimed is exhausted_row
        assert exhausted_row.state == "failed"
        assert exhausted_row.outcome == "attempts_exhausted"
        assert exhausted_row.lease_token is None


def test_reap_expired_records():
    now = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
    mock_qs = MagicMock()

    with patch("core.common.notifications.lease.django_transaction.atomic"):
        # None found
        mock_qs.select_for_update.return_value.filter.return_value.order_by.return_value.values_list.return_value.__getitem__.return_value = []
        assert reap_expired_records(mock_qs, now=now) == 0

        # Expired records updated
        mock_qs.select_for_update.return_value.filter.return_value.order_by.return_value.values_list.return_value.__getitem__.return_value = [1, 2]
        mock_qs.filter.return_value.update.return_value = 2
        assert reap_expired_records(mock_qs, now=now) == 2
        mock_qs.filter.assert_called_with(pk__in=[1, 2])


def test_complete_leased_record():
    now = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
    token = uuid4()
    mock_qs = MagicMock()

    # Case 1: Terminal outcome (sent)
    row = MagicMock()
    row.pk = 42
    row.attempts = 1
    row.lease_token = token
    mock_qs.filter.return_value.update.return_value = 1

    outcome = DeliveryOutcome(state="sent", code="accepted")
    success = complete_leased_record(mock_qs, row=row, outcome=outcome, now=now)

    assert success is True
    mock_qs.filter.assert_called_with(pk=42, state="leased", lease_token=token, lease_until__gt=now)
    update_kwargs = mock_qs.filter.return_value.update.call_args.kwargs
    assert update_kwargs["state"] == "sent"
    assert update_kwargs["outcome"] == "accepted"
    assert update_kwargs["lease_token"] is None
    assert update_kwargs["lease_until"] is None
    assert update_kwargs["finished_at"] == now

    # Case 2: Retry outcome with backoff delay
    outcome_retry = DeliveryOutcome(state="retry", code="network_error")
    delay = timedelta(seconds=60)
    success = complete_leased_record(
        mock_qs, row=row, outcome=outcome_retry, now=now, backoff_delay=delay, max_attempts=5
    )
    assert success is True
    update_kwargs = mock_qs.filter.return_value.update.call_args.kwargs
    assert update_kwargs["state"] == "pending"
    assert update_kwargs["outcome"] == "network_error"
    assert update_kwargs["finished_at"] is None
    assert update_kwargs["available_at"] == now + delay

    # Case 3: Retry outcome when attempts exhausted
    row_exhausted = MagicMock()
    row_exhausted.pk = 43
    row_exhausted.attempts = 5
    row_exhausted.lease_token = token
    success = complete_leased_record(mock_qs, row=row_exhausted, outcome=outcome_retry, now=now, max_attempts=5)
    assert success is True
    update_kwargs = mock_qs.filter.return_value.update.call_args.kwargs
    assert update_kwargs["state"] == "failed"
    assert update_kwargs["finished_at"] == now

    # Case 4: Lease lost (update returns 0 rows)
    mock_qs.filter.return_value.update.return_value = 0
    success = complete_leased_record(mock_qs, row=row, outcome=outcome, now=now)
    assert success is False
