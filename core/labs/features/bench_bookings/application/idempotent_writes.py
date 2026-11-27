"""Replay-safe bench booking create, update and cancel when the client sends an ``Idempotency-Key``.

Race guard: a transaction-scoped advisory lock on (actor, key) serializes requests that share a key, and the
``bench_write_receipt_actor_key_uniq`` constraint backs it in the table. The write and its receipt commit in one
transaction, so a failed write stores nothing and the same key may be retried. Response standard RW-6.
"""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.utils import timezone

from core.labs.features.bench_bookings.exceptions import BenchBookingIdempotencyKeyReuse
from core.labs.models import BenchBooking, BenchBookingWriteReceipt

RECEIPT_LIFETIME = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class IdempotentWriteResult:
    status_code: int
    response_body: dict[str, Any]
    replayed: bool


def run_idempotent_booking_write(
    *,
    actor: Any,
    operation: str,
    key: str,
    request_values: Mapping[str, Any],
    write: Callable[[], BenchBooking],
    project_response: Callable[[BenchBooking], tuple[int, dict[str, Any]]],
) -> IdempotentWriteResult:
    """Run ``write`` once per (actor, key); a repeat with the same input returns the first response.

    ``request_values`` must name the operation's target (booking id) and the validated input, so a key reused
    for another booking or body is refused with ``idempotency_key_reuse``. ``project_response`` turns the written
    booking into the success status and JSON-ready envelope that is stored and replayed.
    """
    request_hash = _request_hash(operation=operation, request_values=request_values)
    with transaction.atomic():
        _lock_key(actor_id=actor.pk, key=key)
        now = timezone.now()
        BenchBookingWriteReceipt.objects.filter(actor=actor, key=key, expires_at__lte=now).delete()
        receipt = BenchBookingWriteReceipt.objects.filter(actor=actor, key=key).first()
        if receipt is not None:
            if receipt.operation != operation or receipt.request_hash != request_hash:
                raise BenchBookingIdempotencyKeyReuse("Idempotency-Key was already used with a different request.")
            return IdempotentWriteResult(
                status_code=receipt.status_code, response_body=receipt.response_body, replayed=True
            )

        booking = write()
        status_code, body = project_response(booking)
        body = json.loads(json.dumps(body, cls=DjangoJSONEncoder))
        BenchBookingWriteReceipt.objects.create(
            actor=actor,
            booking=booking,
            operation=operation,
            key=key,
            request_hash=request_hash,
            status_code=status_code,
            response_body=body,
            expires_at=now + RECEIPT_LIFETIME,
        )
    return IdempotentWriteResult(status_code=status_code, response_body=body, replayed=False)


def _request_hash(*, operation: str, request_values: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        {"operation": operation, **request_values}, sort_keys=True, separators=(",", ":"), cls=DjangoJSONEncoder
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _lock_key(*, actor_id: int, key: str) -> None:
    lock_name = f"bench-booking-write:{actor_id}:{key}"
    lock_number = int.from_bytes(hashlib.sha256(lock_name.encode()).digest()[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_number])
