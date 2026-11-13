"""Create a bench booking under the bench row lock."""

from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.bench_bookings.queries import (
    bench_downtime_blocker,
    bench_parent_blocker,
    conflicting_bench_bookings,
    project_exists,
)
from core.labs.models import BenchBooking

from . import policies
from .booking_codes import generate_booking_code
from .locks import lock_benches
from .notification_intents import record_notification


@dataclass(frozen=True, slots=True)
class CreateBenchBookingInput:
    bench_id: int
    starts_at: datetime
    ends_at: datetime
    reason: str = ""
    project_id: int | None = None


def create_bench_booking(*, actor, data: CreateBenchBookingInput) -> BenchBooking:
    policies.ensure_valid_period(data.starts_at, data.ends_at)
    policies.ensure_minimum_duration(data.starts_at, data.ends_at)
    policies.ensure_startable(data.starts_at, now=timezone.now())
    with transaction.atomic():
        bench = lock_benches((data.bench_id,))[data.bench_id]
        policies.ensure_bench_accepts_bookings(bench, parent_blocker=bench_parent_blocker(bench=bench))
        if data.project_id is not None:
            policies.ensure_project_exists(exists=project_exists(project_id=data.project_id))
        conflicts = conflicting_bench_bookings(
            bench_id=data.bench_id,
            starts_at=data.starts_at,
            ends_at=data.ends_at,
        )
        policies.ensure_no_conflicting_bookings(has_conflicts=conflicts.exists())
        policies.ensure_no_downtime(
            bench_downtime_blocker(bench=bench, starts_at=data.starts_at, ends_at=data.ends_at)
        )
        for _ in range(3):
            booking = BenchBooking(
                bench_id=data.bench_id,
                starts_at=data.starts_at,
                ends_at=data.ends_at,
                reason=data.reason,
                project_id=data.project_id,
                booking_code=generate_booking_code(
                    bench_id=data.bench_id,
                    starts_at=data.starts_at,
                    ends_at=data.ends_at,
                ),
                approval_status=policies.default_approval_status(data.ends_at - data.starts_at),
            )
            try:
                with transaction.atomic():
                    booking.save(actor=actor)
            except IntegrityError as error:
                if not _is_booking_code_collision(error):
                    raise
            else:
                record_notification(booking=booking, kind="created")
                return booking
    raise IntegrityError("Could not generate a unique booking code after three attempts.")


def _is_booking_code_collision(error: IntegrityError) -> bool:
    return "booking_code" in str(error.__cause__ or error)
