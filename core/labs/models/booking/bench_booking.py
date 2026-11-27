from django.db import models
from django.db.models import Q
from django.conf import settings

from .base import Booking, no_overlap_constraint


class BenchBooking(Booking):
    bench = models.ForeignKey(
        "labs.Bench",
        related_name="bookings",
        on_delete=models.PROTECT,
    )

    def __str__(self) -> str:
        return f"{self.booking_code}: {self.bench}"

    class Meta(Booking.Meta):
        app_label = "labs"
        constraints = [
            *Booking.Meta.constraints,
            no_overlap_constraint(name="bench_booking_no_overlap", resource_field="bench"),
        ]
        indexes = [
            models.Index(
                fields=("bench", "starts_at", "ends_at"),
                name="bench_booking_schedule_idx",
            ),
            models.Index(
                fields=("bench", "status", "approval_status"),
                name="bench_booking_state_idx",
            ),
        ]


class BenchBookingDecisionReceipt(models.Model):
    """Actor/action-scoped replay result for a bench booking approval decision."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="bench_booking_decision_receipts",
        on_delete=models.PROTECT,
    )
    booking = models.ForeignKey(BenchBooking, related_name="decision_receipts", on_delete=models.PROTECT)
    operation = models.CharField(max_length=8, choices=(("approve", "Approve"), ("reject", "Reject")))
    key = models.CharField(max_length=36)
    request_hash = models.CharField(max_length=64)
    status_code = models.PositiveSmallIntegerField()
    response_body = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        app_label = "labs"
        constraints = [
            models.UniqueConstraint(
                fields=("actor", "operation", "booking", "key"),
                name="bench_decision_actor_op_book_key_uniq",
            ),
            models.CheckConstraint(
                condition=Q(status_code__gte=200, status_code__lt=300),
                name="bench_decision_receipt_success_only",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__gt=models.F("created_at")),
                name="bench_decision_receipt_expiry_valid",
            ),
        ]
        indexes = [models.Index(fields=("expires_at",), name="bench_decision_receipt_exp_idx")]


class BenchBookingWriteOperation(models.TextChoices):
    CREATE = "create", "Create"
    UPDATE = "update", "Update"
    CANCEL = "cancel", "Cancel"


class BenchBookingWriteReceipt(models.Model):
    """Stored first response of a bench booking create, update or cancel sent with an ``Idempotency-Key``.

    One key per actor: a key reused for another operation, booking or body is refused. Only successful
    responses are stored, so a failed request leaves nothing behind and may be retried with the same key.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="bench_booking_write_receipts",
        on_delete=models.PROTECT,
    )
    booking = models.ForeignKey(BenchBooking, related_name="write_receipts", on_delete=models.PROTECT)
    operation = models.CharField(max_length=8, choices=BenchBookingWriteOperation.choices)
    key = models.CharField(max_length=36)
    request_hash = models.CharField(max_length=64)
    status_code = models.PositiveSmallIntegerField()
    response_body = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        app_label = "labs"
        constraints = [
            models.UniqueConstraint(fields=("actor", "key"), name="bench_write_receipt_actor_key_uniq"),
            models.CheckConstraint(
                condition=Q(operation__in=BenchBookingWriteOperation.values),
                name="bench_write_receipt_valid_operation",
            ),
            models.CheckConstraint(
                condition=Q(status_code__gte=200, status_code__lt=300),
                name="bench_write_receipt_success_only",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__gt=models.F("created_at")),
                name="bench_write_receipt_expiry_valid",
            ),
        ]
        indexes = [models.Index(fields=("expires_at",), name="bench_write_receipt_exp_idx")]
