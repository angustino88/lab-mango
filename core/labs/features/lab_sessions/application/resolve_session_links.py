"""Derive a session's access type and its booking, bench and user links from master data."""

from dataclasses import dataclass
from datetime import datetime

from django.db import transaction

from core.labs.features.bench_bookings.public import SessionBookingFacts, find_session_booking_facts
from core.labs.features.equipment.public import bench_id_at
from core.labs.models import BookingApprovalStatus, BookingStatus, LabSessionLog, SessionAccessType
from core.users.public import resolve_user_id_for_login_name

RESOLVE_BATCH_SIZE = 500


@dataclass(frozen=True)
class SessionLinks:
    access_type: str
    booking_id: int | None
    bench_id: int | None
    user_id: int | None

    def as_fields(self) -> dict[str, object]:
        return {
            "access_type": self.access_type,
            "booking_id": self.booking_id,
            "bench_id": self.bench_id,
            "user_id": self.user_id,
        }


def classify_access(
    *,
    booking_code: str | None,
    login_time: datetime | None,
    bench_id: int | None,
    booking: SessionBookingFacts | None,
) -> tuple[str, int | None]:
    """Return the access type and the verified booking id (owner decisions O22, O21).

    No code is ad hoc. A code is booked only when its booking is approved, not cancelled, on the bench
    the computer stood at, and the login falls inside the booking window. Expired and completed
    bookings still verify: a used booking can end as expired while activation has no caller.
    """
    if booking_code is None:
        return SessionAccessType.AD_HOC, None
    verified = (
        booking is not None
        and login_time is not None
        and bench_id is not None
        and booking.bench_id == bench_id
        and booking.approval_status == BookingApprovalStatus.APPROVED
        and booking.status != BookingStatus.CANCELLED
        and booking.starts_at <= login_time < booking.ends_at
    )
    if verified and booking is not None:
        return SessionAccessType.BOOKED, booking.booking_id
    return SessionAccessType.UNVERIFIED_BOOKING, None


def resolve_links(
    *,
    equipment_id: int | None,
    login_time: datetime | None,
    booking_code: str | None,
    remote_user: str | None,
) -> SessionLinks:
    """Read the facts for one session and classify it. At most three queries; no writes."""
    bench_id = (
        bench_id_at(equipment_id=equipment_id, at=login_time)
        if equipment_id is not None and login_time is not None
        else None
    )
    booking = find_session_booking_facts(booking_code=booking_code) if booking_code is not None else None
    access_type, booking_id = classify_access(
        booking_code=booking_code, login_time=login_time, bench_id=bench_id, booking=booking
    )
    return SessionLinks(
        access_type=access_type,
        booking_id=booking_id,
        bench_id=bench_id,
        user_id=resolve_user_id_for_login_name(login_name=remote_user),
    )


def resolve_session_links(*, batch_size: int = RESOLVE_BATCH_SIZE, max_batches: int | None = None) -> int:
    """Fill access type and links on session logs stored before they existed. Returns rows filled.

    Rows whose ``access_type`` is null are taken in primary-key order, one transaction per batch.
    Race guard: ``select_for_update(skip_locked=True)``, and each update re-checks
    ``access_type__isnull=True``, so concurrent runs never fill a row twice. Idempotent and
    resumable: a filled row is never selected again.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")
    filled = 0
    batches = 0
    while max_batches is None or batches < max_batches:
        with transaction.atomic():
            rows = list(
                LabSessionLog.objects.select_for_update(skip_locked=True)
                .filter(access_type__isnull=True)
                .order_by("pk")
                .values("pk", "computing_equipment_id", "login_time", "booking_code", "remote_user")[:batch_size]
            )
            if not rows:
                break
            for row in rows:
                links = resolve_links(
                    equipment_id=row["computing_equipment_id"],
                    login_time=row["login_time"],
                    booking_code=row["booking_code"],
                    remote_user=row["remote_user"],
                )
                filled += LabSessionLog.objects.filter(pk=row["pk"], access_type__isnull=True).update(
                    **links.as_fields()
                )
        batches += 1
    return filled


__all__ = ["RESOLVE_BATCH_SIZE", "SessionLinks", "classify_access", "resolve_links", "resolve_session_links"]
