"""Overdue reminder emails for loan slips (equipment booking revision 2, phase 3).

Schedule (OD4): at the due time, one day later, then daily, capped at one week (slots 0 to 7).
One email per slip lists every overdue item on it. Recipient: the borrower's account email, or
``borrower_contact`` when it is an email address; slips without either are only listed for the
coordinator (``GET /api/labs/equipment-loans?overdue=true``).

Idempotency: ``equipment_loan_reminder_once_per_slot`` makes each slot at most one row, so
re-running the collector creates nothing new. Missed earlier slots are not sent late; only the
current slot is. Delivery: rows are claimed with the shared lease protocol (``SKIP LOCKED``), the
email is sent outside any transaction, and completion is fenced by the lease token.
"""

import logging
import random
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Min
from django.utils import timezone

from core.common.notifications import (
    DeliveryOutcome,
    calculate_backoff_delay,
    claim_leased_record,
    complete_leased_record,
    verify_lease_ownership,
)
from core.infrastructure.email.service import send_email
from core.labs.models import EquipmentLoan, EquipmentLoanBatch, EquipmentLoanReminder
from core.labs.models.resource.equipment.loan import REMINDER_LAST_SLOT

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
LEASE_SECONDS = 120
REMINDER_TTL = timedelta(days=1)
TEMPLATE = "emails/equipment_overdue_reminder.html"


@transaction.atomic
def collect_overdue_reminders(*, now: datetime | None = None, limit: int = 500) -> int:
    """Create the current reminder slot for each slip with overdue open loans. Safe to re-run."""
    now = now or timezone.now()
    overdue = (
        EquipmentLoan.objects.filter(returned_at__isnull=True, due_at__lte=now)
        .values("batch_id")
        .annotate(first_due=Min("due_at"))
        .order_by("batch_id")[:limit]
    )
    slots = {row["batch_id"]: (now - row["first_due"]) // timedelta(days=1) for row in overdue}
    slots = {batch_id: slot for batch_id, slot in slots.items() if slot <= REMINDER_LAST_SLOT}
    batches = EquipmentLoanBatch.objects.select_related("borrower").in_bulk(list(slots))
    rows = []
    for batch_id, slot in slots.items():
        recipient = reminder_recipient(batches[batch_id])
        if recipient:
            rows.append(
                EquipmentLoanReminder(
                    batch_id=batch_id,
                    slot=slot,
                    recipient_email=recipient,
                    created_at=now,
                    available_at=now,
                    expires_at=now + REMINDER_TTL,
                )
            )
    before = EquipmentLoanReminder.objects.filter(batch_id__in=[row.batch_id for row in rows]).count()
    EquipmentLoanReminder.objects.bulk_create(rows, ignore_conflicts=True)
    created = EquipmentLoanReminder.objects.filter(batch_id__in=[row.batch_id for row in rows]).count() - before
    logger.info(
        "equipment.reminders.collected", extra={"reminders_created": created, "reminder_candidates": len(rows)}
    )
    return created


def deliver_overdue_reminders(*, limit: int = 20) -> dict[str, int]:
    """Send up to ``limit`` pending reminders. Deliberately not atomic: no lock or transaction is held during I/O."""
    counts = {"claimed": 0, "sent": 0, "retry": 0, "skipped": 0, "failed": 0, "expired": 0, "fenced": 0}
    queryset = EquipmentLoanReminder.objects.all()
    for _ in range(max(1, min(limit, 100))):
        now = timezone.now()
        row = claim_leased_record(queryset, now=now, lease_seconds=LEASE_SECONDS, max_attempts=MAX_ATTEMPTS)
        if row is None:
            break
        counts["claimed"] += 1
        if row.state in ("failed", "expired"):  # finalized by the claim (attempts exhausted or stale)
            counts[row.state] += 1
            continue
        token = row.lease_token
        lines = list(
            EquipmentLoan.objects.filter(batch_id=row.batch_id, returned_at__isnull=True, due_at__lte=now)
            .select_related("equipment")
            .order_by("due_at", "pk")
        )
        if not lines:
            outcome = DeliveryOutcome(state="skipped", code="returned")
        elif not verify_lease_ownership(row, token=token, now=timezone.now()):
            counts["fenced"] += 1
            continue
        else:
            batch = EquipmentLoanBatch.objects.select_related("borrower").get(pk=row.batch_id)
            sent = send_email(
                subject=_subject(row.slot, len(lines)),
                context=reminder_context(batch, lines, slot=row.slot, now=now),
                template=TEMPLATE,
                receivers=[row.recipient_email],
                log_failure_details=False,
            )
            outcome = (
                DeliveryOutcome(state="sent", code="sent")
                if sent
                else DeliveryOutcome(state="retry", code="send_failed")
            )
        backoff = (
            calculate_backoff_delay(attempt=row.attempts, jitter=random.random()) if outcome.state == "retry" else None
        )
        if not complete_leased_record(
            queryset, row=row, outcome=outcome, now=timezone.now(), max_attempts=MAX_ATTEMPTS, backoff_delay=backoff
        ):
            counts["fenced"] += 1
            continue
        key = "failed" if outcome.state == "retry" and row.attempts >= MAX_ATTEMPTS else outcome.state
        counts[key] += 1
    logger.info("equipment.reminders.delivered", extra={f"reminders_{key}": value for key, value in counts.items()})
    return counts


def reminder_recipient(batch: EquipmentLoanBatch) -> str | None:
    """The borrower's account email, else ``borrower_contact`` when it is an email address."""
    user = batch.borrower
    if user is not None and user.is_active and user.email:
        return user.email
    contact = (batch.borrower_contact or "").strip()
    try:
        validate_email(contact)
    except ValidationError:
        return None
    return contact


def reminder_context(batch: EquipmentLoanBatch, lines: list[EquipmentLoan], *, slot: int, now: datetime) -> dict:
    """Allowlisted facts for the template; free text is rendered escaped by the template engine."""
    return {
        "borrower_name": batch.borrower_label,
        "purpose": batch.purpose,
        "final_reminder": slot >= REMINDER_LAST_SLOT,
        "items": [
            {
                "sku": line.equipment.sku,
                "name": line.equipment.name,
                "due_at": timezone.localtime(line.due_at),
                "days_overdue": (now - line.due_at) // timedelta(days=1),
            }
            for line in lines
        ],
    }


def _subject(slot: int, count: int) -> str:
    noun = "item" if count == 1 else "items"
    prefix = "Final reminder" if slot >= REMINDER_LAST_SLOT else "Reminder"
    return f"{prefix}: please return {count} borrowed {noun}"


__all__ = (
    "collect_overdue_reminders",
    "deliver_overdue_reminders",
    "reminder_context",
    "reminder_recipient",
)
