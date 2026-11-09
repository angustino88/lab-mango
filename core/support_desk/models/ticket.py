"""Support ticket model."""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import connection, models, transaction
from django.db.models import F, Q
from django.utils import timezone

from core.support_desk.contracts import (
    IMPACT_CHOICES,
    RESOLUTION_CODE_CHOICES,
    TICKET_SOURCE_CHOICES,
    TICKET_TYPE_CHOICES,
    URGENCY_CHOICES,
    TicketSource,
    TicketType,
)


def get_next_ticket_number() -> int:
    """Acquire the next sequential ticket number atomically."""
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute("SELECT nextval('support_ticket_number_seq');")
            return cursor.fetchone()[0]
        # Fallback for SQLite or test databases without native sequence
        with transaction.atomic():
            max_num = SupportTicket.objects.aggregate(max_val=models.Max("number"))["max_val"] or 0
            return max_num + 1


class SupportTicket(models.Model):
    """Core ticket entity representing a user incident or inquiry."""

    key = models.CharField(max_length=32, unique=True, editable=False)
    number = models.BigIntegerField(unique=True, editable=False)
    subject = models.CharField(max_length=200)
    description = models.TextField()

    ticket_type = models.CharField(
        max_length=20,
        choices=TICKET_TYPE_CHOICES,
        default=TicketType.INCIDENT.value,
        db_index=True,
    )
    source = models.CharField(
        max_length=20,
        choices=TICKET_SOURCE_CHOICES,
        default=TicketSource.WEB.value,
    )
    impact = models.CharField(max_length=1, choices=IMPACT_CHOICES, blank=True, default="")
    urgency = models.CharField(max_length=1, choices=URGENCY_CHOICES, blank=True, default="")
    external_reference = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Reference in an external system (vendor RMA / case number, legacy Jira key...).",
    )

    category = models.ForeignKey(
        "support_desk.SupportCategory",
        on_delete=models.PROTECT,
        related_name="tickets",
    )
    priority = models.ForeignKey(
        "support_desk.SupportPriority",
        on_delete=models.PROTECT,
        related_name="tickets",
    )
    status = models.ForeignKey(
        "support_desk.SupportStatus",
        on_delete=models.PROTECT,
        related_name="tickets",
    )

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_support_tickets",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_support_tickets",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_support_tickets",
    )
    team = models.ForeignKey(
        "support_desk.SupportTeam",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
    )
    labels = models.ManyToManyField(
        "support_desk.SupportLabel",
        blank=True,
        related_name="tickets",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
        help_text="Parent ticket (one level of sub-tickets only).",
    )
    due_date = models.DateField(
        null=True,
        blank=True,
        help_text="Requester/agent-set target date, independent of the SLA.",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    last_activity_at = models.DateTimeField(default=timezone.now, db_index=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # --- SLA ---------------------------------------------------------------
    response_due_at = models.DateTimeField(null=True, blank=True)
    resolution_due_at = models.DateTimeField(null=True, blank=True)
    sla_paused_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set while the ticket sits in a status that pauses SLA clocks.",
    )
    sla_paused_seconds = models.PositiveBigIntegerField(
        default=0,
        help_text="Total seconds the SLA clocks have been paused (already added to the due dates).",
    )
    response_breached_at = models.DateTimeField(null=True, blank=True)
    resolution_breached_at = models.DateTimeField(null=True, blank=True)

    reopen_count = models.PositiveIntegerField(default=0)
    resolution_code = models.CharField(max_length=20, choices=RESOLUTION_CODE_CHOICES, blank=True, default="")
    resolution_summary = models.TextField(blank=True, default="")
    root_cause = models.TextField(blank=True, default="")
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_support_tickets",
    )

    # --- Customer satisfaction (CSAT) -------------------------------------
    csat_score = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    csat_comment = models.TextField(blank=True, default="")
    csat_submitted_at = models.DateTimeField(null=True, blank=True)

    version = models.PositiveIntegerField(default=1)
    idempotency_key = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        unique=True,
        db_index=True,
    )

    class Meta:
        verbose_name = "Support Ticket"
        verbose_name_plural = "Support Tickets"
        ordering = ["priority__rank", "created_at", "id"]
        indexes = [
            models.Index(fields=["status", "priority", "created_at"], name="idx_ticket_queue"),
            models.Index(fields=["assignee", "status"], name="idx_ticket_assignee_status"),
            models.Index(fields=["requester", "created_at"], name="idx_ticket_req_created"),
            models.Index(fields=["category"], name="idx_ticket_category"),
            models.Index(fields=["team", "status"], name="idx_ticket_team_status"),
            models.Index(fields=["resolution_due_at"], name="idx_ticket_resolution_due"),
            models.Index(fields=["response_due_at"], name="idx_ticket_response_due"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(csat_score__isnull=True) | (Q(csat_score__gte=1) & Q(csat_score__lte=5)),
                name="ticket_csat_score_1_to_5",
            ),
            models.CheckConstraint(condition=~Q(parent=F("pk")), name="ticket_parent_not_self"),
        ]

    def __str__(self) -> str:
        return f"[{self.key}] {self.subject}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = get_next_ticket_number()
        if not self.key:
            self.key = f"SUP-{self.number:06d}"
        super().save(*args, **kwargs)
