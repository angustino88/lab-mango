"""Competing-worker lease claiming, fencing, and cleanup protocol."""

import uuid
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import transaction as django_transaction
from django.db.models import Q, QuerySet

from .contracts import DeliveryOutcome, DeliveryState


def claim_leased_record(
    queryset: QuerySet | Any,
    *,
    now: datetime,
    lease_seconds: int = 120,
    max_attempts: int = 5,
    transaction: Any = None,
    state_field: str = "state",
    available_at_field: str = "available_at",
    expires_at_field: str = "expires_at",
    lease_token_field: str = "lease_token",
    lease_until_field: str = "lease_until",
    attempts_field: str = "attempts",
    outcome_field: str = "outcome",
    finished_at_field: str = "finished_at",
) -> Any | None:
    """Atomically claim one available outbox record using PostgreSQL SKIP LOCKED.

    Recovers expired leases where lease_until <= now.
    Exhausted or expired rows are marked accordingly and returned.
    """
    tx = transaction or django_transaction
    with tx.atomic():
        pending_cond = Q(**{state_field: DeliveryState.PENDING.value, f"{available_at_field}__lte": now})
        expired_lease_cond = Q(**{state_field: DeliveryState.LEASED.value, f"{lease_until_field}__lte": now})

        row = (
            queryset.select_for_update(skip_locked=True)
            .filter(
                pending_cond | expired_lease_cond,
                **{f"{expires_at_field}__gt": now},
            )
            .order_by(expires_at_field, available_at_field, "id")
            .first()
        )
        if row is None:
            return None

        expires_at = getattr(row, expires_at_field)
        attempts = getattr(row, attempts_field)

        if expires_at <= now or attempts >= max_attempts:
            is_expired = expires_at <= now
            final_state = DeliveryState.EXPIRED.value if is_expired else DeliveryState.FAILED.value
            final_outcome = "expired" if is_expired else "attempts_exhausted"

            setattr(row, state_field, final_state)
            setattr(row, outcome_field, final_outcome)
            setattr(row, lease_token_field, None)
            setattr(row, lease_until_field, None)
            setattr(row, finished_at_field, now)
            row.save(
                update_fields=(
                    state_field,
                    outcome_field,
                    lease_token_field,
                    lease_until_field,
                    finished_at_field,
                )
            )
            return row

        new_token = uuid.uuid4()
        new_until = now + timedelta(seconds=lease_seconds)

        setattr(row, state_field, DeliveryState.LEASED.value)
        setattr(row, lease_token_field, new_token)
        setattr(row, lease_until_field, new_until)
        setattr(row, attempts_field, attempts + 1)
        row.save(
            update_fields=(
                state_field,
                lease_token_field,
                lease_until_field,
                attempts_field,
            )
        )
        return row


def verify_lease_ownership(
    row: Any,
    *,
    token: UUID | None,
    now: datetime,
    state_field: str = "state",
    lease_token_field: str = "lease_token",
    lease_until_field: str = "lease_until",
) -> bool:
    """Check if the record currently holds a valid, unexpired lease with matching token."""
    if token is None:
        return False
    state_val = getattr(row, state_field, None)
    token_val = getattr(row, lease_token_field, None)
    until_val = getattr(row, lease_until_field, None)

    return state_val == DeliveryState.LEASED.value and token_val == token and until_val is not None and until_val > now


def reap_expired_records(
    queryset: QuerySet | Any,
    *,
    now: datetime,
    limit: int = 100,
    transaction: Any = None,
    state_field: str = "state",
    expires_at_field: str = "expires_at",
    lease_token_field: str = "lease_token",
    lease_until_field: str = "lease_until",
    outcome_field: str = "outcome",
    finished_at_field: str = "finished_at",
) -> int:
    """Batch-reap expired outbox rows without touching active, unexpired leases."""
    bounded_limit = min(max(limit, 1), 100)
    tx = transaction or django_transaction
    with tx.atomic():
        pending_cond = Q(**{state_field: DeliveryState.PENDING.value})
        expired_lease_cond = Q(**{state_field: DeliveryState.LEASED.value, f"{lease_until_field}__lte": now})

        ids = list(
            queryset.select_for_update(skip_locked=True)
            .filter(
                pending_cond | expired_lease_cond,
                **{f"{expires_at_field}__lte": now},
            )
            .order_by(expires_at_field, "id")
            .values_list("pk", flat=True)[:bounded_limit]
        )
        if not ids:
            return 0

        update_kwargs = {
            state_field: DeliveryState.EXPIRED.value,
            outcome_field: "expired",
            lease_token_field: None,
            lease_until_field: None,
            finished_at_field: now,
        }
        return queryset.filter(pk__in=ids).update(**update_kwargs)


def complete_leased_record(
    queryset: QuerySet | Any,
    *,
    row: Any,
    outcome: DeliveryOutcome | str,
    now: datetime,
    max_attempts: int = 5,
    outcome_code: str = "",
    backoff_delay: timedelta | None = None,
    state_field: str = "state",
    outcome_field: str = "outcome",
    lease_token_field: str = "lease_token",
    lease_until_field: str = "lease_until",
    finished_at_field: str = "finished_at",
    available_at_field: str = "available_at",
    attempts_field: str = "attempts",
) -> bool:
    """Atomically complete a leased record if the worker still holds the lease."""
    if isinstance(outcome, DeliveryOutcome):
        state = outcome.state
        code = outcome.code
    else:
        state = outcome
        code = outcome_code

    attempts = getattr(row, attempts_field, 0)
    if state == "retry":
        state = DeliveryState.PENDING.value if attempts < max_attempts else DeliveryState.FAILED.value

    changes: dict[str, Any] = {
        state_field: state,
        outcome_field: code,
        lease_token_field: None,
        lease_until_field: None,
        finished_at_field: None if state == DeliveryState.PENDING.value else now,
    }
    if state == DeliveryState.PENDING.value and backoff_delay is not None:
        changes[available_at_field] = now + backoff_delay

    lease_token = getattr(row, lease_token_field)
    filter_kwargs = {
        "pk": row.pk,
        state_field: DeliveryState.LEASED.value,
        lease_token_field: lease_token,
        f"{lease_until_field}__gt": now,
    }
    changed = queryset.filter(**filter_kwargs).update(**changes)
    return bool(changed)
