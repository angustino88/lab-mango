"""Physical custody of an equipment item: who holds it and until when (redesign step 3).

A booking is a calendar entry; a loan is custody. A unit on loan has no active placement (enforced
by the equipment commands under the ``Equipment`` row lock). Overdue is computed
(``returned_at IS NULL AND due_at < now()``), never stored. Loans have no code of their own (OD4).
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

CONDITION_NOTE_MAX_LENGTH = 255
BORROWER_NAME_MAX_LENGTH = 255
PURPOSE_MAX_LENGTH = 2000
IDEMPOTENCY_KEY_MAX_LENGTH = 128


class LoanCloseReason(models.TextChoices):
    RETURNED = "returned", _("Returned")
    LOST = "lost", _("Lost")


class EquipmentLoanBatch(TimeStampedModel):
    """The loan slip: one borrower and purpose for one or more items handed over together.

    The borrower is a user account or, for people without one, a name (at least one of the two).
    """

    borrower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="equipment_loan_batches",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    borrower_name = models.CharField(max_length=BORROWER_NAME_MAX_LENGTH, blank=True, default="")
    borrower_contact = models.CharField(
        max_length=255, blank=True, default="", help_text="Email or phone of a borrower without an account."
    )
    purpose = models.CharField(max_length=PURPOSE_MAX_LENGTH, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="equipment_loan_batches_created",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    idempotency_key = models.CharField(max_length=IDEMPOTENCY_KEY_MAX_LENGTH, blank=True, default="")
    request_hash = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        app_label = "labs"
        ordering = ("-created", "-id")
        constraints = [
            models.CheckConstraint(
                condition=Q(borrower__isnull=False) | ~Q(borrower_name=""),
                name="equipment_loan_batch_has_borrower",
            ),
            models.UniqueConstraint(
                fields=("created_by", "idempotency_key"),
                condition=~Q(idempotency_key=""),
                nulls_distinct=False,
                name="equipment_loan_batch_idempotency_uniq",
            ),
        ]
        indexes = [models.Index(fields=("borrower", "-created"), name="equipment_loan_batch_borr_idx")]

    @property
    def borrower_label(self) -> str:
        if self.borrower_name:
            return self.borrower_name
        user = self.borrower
        return (user.display_name or user.username) if user else ""

    def __str__(self) -> str:
        return f"Loan batch {self.pk} for {self.borrower_label}"


class EquipmentLoan(TimeStampedModel):
    equipment = models.ForeignKey("labs.Equipment", related_name="loans", on_delete=models.PROTECT)
    batch = models.ForeignKey(EquipmentLoanBatch, related_name="loans", on_delete=models.PROTECT)
    booking = models.OneToOneField(
        "labs.EquipmentBooking",
        related_name="loan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="The booking this loan fulfils; empty for custody that is not a booking.",
    )
    handed_over_at = models.DateTimeField()
    handed_over_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="equipment_loans_handed_over",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    due_at = models.DateTimeField()
    returned_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="equipment_loans_received",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    condition_out = models.CharField(max_length=CONDITION_NOTE_MAX_LENGTH, blank=True, default="")
    condition_in = models.CharField(max_length=CONDITION_NOTE_MAX_LENGTH, blank=True, default="")
    close_reason = models.CharField(max_length=16, choices=LoanCloseReason.choices, null=True, blank=True)

    class Meta:
        app_label = "labs"
        ordering = ("-handed_over_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("equipment",), condition=Q(returned_at__isnull=True), name="one_active_loan_per_equipment"
            ),
            models.CheckConstraint(
                condition=(Q(returned_at__isnull=True, close_reason__isnull=True))
                | (Q(returned_at__isnull=False, close_reason__isnull=False)),
                name="equipment_loan_closed_has_reason",
            ),
            models.CheckConstraint(
                condition=Q(close_reason__isnull=True) | Q(close_reason__in=LoanCloseReason.values),
                name="equipment_loan_close_reason_valid",
            ),
            models.CheckConstraint(
                condition=Q(due_at__gt=F("handed_over_at")), name="equipment_loan_due_after_handover"
            ),
            models.CheckConstraint(
                condition=Q(returned_at__isnull=True) | Q(returned_at__gte=F("handed_over_at")),
                name="equipment_loan_returned_after_handover",
            ),
        ]
        indexes = [
            models.Index(
                fields=("due_at",), condition=Q(returned_at__isnull=True), name="equipment_loan_open_due_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"Loan {self.pk} of {self.equipment_id} (batch {self.batch_id})"
