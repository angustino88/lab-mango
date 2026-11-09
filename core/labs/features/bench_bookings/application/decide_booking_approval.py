"""Approve or reject a pending bench booking under bench and booking row locks."""

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.utils import timezone

from core.common.api.permissions import is_authenticated
from core.labs.features.bench_bookings.exceptions import (
    BenchBookingConflict,
    BenchBookingIdempotencyKeyReuse,
    BenchBookingPermissionDenied,
)
from core.labs.models import (
    BenchBooking,
    BenchBookingDecisionReceipt,
    BookingApprovalStatus,
    BookingStatus,
)
from core.users.public import LabsRole, has_labs_role

from .locks import lock_benches

MAX_REJECTION_REASON_LENGTH = 500


@dataclass(frozen=True, slots=True)
class DecideBenchBookingApprovalInput:
    booking_id: int
    decision: str
    idempotency_key: str
    rejection_reason: str = ""


def decide_bench_booking_approval(
    *, actor: Any, data: DecideBenchBookingApprovalInput, project_response: Any
) -> "DecideBenchBookingApprovalResult":
    """Apply one coordinator/admin decision to an actionable pending reservation.

    Race guard: lock the bench before the booking, matching every schedule writer. The second
    booking read under lock validates the observed bench and current state before mutation.
    """
    if not is_authenticated(actor) or not has_labs_role(actor, LabsRole.COORDINATOR):
        raise BenchBookingPermissionDenied("Only a lab coordinator or administrator can decide booking approval.")

    if data.decision not in {BookingApprovalStatus.APPROVED, BookingApprovalStatus.REJECTED}:
        raise ValidationError({"decision": "Choose approved or rejected."})

    rejection_reason = data.rejection_reason.strip()
    if data.decision == BookingApprovalStatus.REJECTED:
        if not rejection_reason:
            raise ValidationError({"reason": "A rejection reason is required."})
        if len(rejection_reason) > MAX_REJECTION_REASON_LENGTH:
            raise ValidationError({"reason": f"Ensure this field has no more than {MAX_REJECTION_REASON_LENGTH} characters."})
    elif data.rejection_reason:
        raise ValidationError({"reason": "A reason is accepted only when rejecting a booking."})

    operation = "approve" if data.decision == BookingApprovalStatus.APPROVED else "reject"
    request_values = {
        "booking_id": data.booking_id,
        "decision": data.decision,
        "rejection_reason": rejection_reason,
    }
    encoded = json.dumps(request_values, sort_keys=True, separators=(",", ":"), cls=DjangoJSONEncoder)
    request_hash = hashlib.sha256(encoded.encode()).hexdigest()
    lock_key = f"bench-booking-decision:{actor.pk}:POST:/api/labs/bench-bookings/{data.booking_id}/actions/{operation}:{data.idempotency_key}"

    with transaction.atomic():
        lock_number = int.from_bytes(hashlib.sha256(lock_key.encode()).digest()[:8], "big", signed=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_number])
        BenchBookingDecisionReceipt.objects.filter(
            actor=actor,
            booking_id=data.booking_id,
            operation=operation,
            key=data.idempotency_key,
            expires_at__lte=timezone.now(),
        ).delete()
        prior_scope_receipt = BenchBookingDecisionReceipt.objects.filter(
            actor=actor,
            key=data.idempotency_key,
            expires_at__gt=timezone.now(),
        ).exclude(booking_id=data.booking_id, operation=operation).first()
        if prior_scope_receipt is not None:
            raise BenchBookingIdempotencyKeyReuse("Idempotency-Key was already used for a different action path.")
        receipt = BenchBookingDecisionReceipt.objects.filter(
            actor=actor,
            booking_id=data.booking_id,
            operation=operation,
            key=data.idempotency_key,
            expires_at__gt=timezone.now(),
        ).first()
        if receipt is not None:
            if receipt.request_hash != request_hash:
                raise BenchBookingIdempotencyKeyReuse("Idempotency-Key was already used with different input.")
            return DecideBenchBookingApprovalResult(
                booking=None,
                status_code=receipt.status_code,
                response_body=receipt.response_body,
                replayed=True,
            )

        observed_bench_id = BenchBooking.objects.values_list("bench_id", flat=True).get(pk=data.booking_id)
        lock_benches((observed_bench_id,))
        booking = BenchBooking.objects.select_for_update().get(pk=data.booking_id)
        if booking.bench_id != observed_bench_id:
            raise BenchBookingConflict("The booking moved concurrently; reload it and retry.")
        if booking.status != BookingStatus.RESERVED or booking.approval_status != BookingApprovalStatus.PENDING:
            raise BenchBookingConflict("Only pending reserved bookings can be approved or rejected.")

        booking.approval_status = data.decision
        booking.approved_by = actor
        booking.approved_at = timezone.now()
        booking.rejection_reason = rejection_reason if data.decision == BookingApprovalStatus.REJECTED else ""
        booking.save(actor=actor)
        response_body = project_response(booking)
        BenchBookingDecisionReceipt.objects.create(
            actor=actor,
            booking=booking,
            operation=operation,
            key=data.idempotency_key,
            request_hash=request_hash,
            status_code=200,
            response_body=response_body,
            expires_at=timezone.now() + timedelta(hours=24),
        )
    return DecideBenchBookingApprovalResult(
        booking=booking,
        status_code=200,
        response_body=response_body,
        replayed=False,
    )


@dataclass(frozen=True, slots=True)
class DecideBenchBookingApprovalResult:
    booking: BenchBooking | None
    status_code: int
    response_body: dict[str, Any]
    replayed: bool


