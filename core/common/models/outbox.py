"""Abstract ledger model for reliable feature-owned transactional outboxes."""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.common.notifications.contracts import DeliveryState


class AbstractOutboxLedger(models.Model):
    """Abstract transactional outbox ledger.

    Features maintain separate tables inheriting from this class,
    preventing cross-domain table contention while enforcing uniform
    delivery semantics and lease invariants.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_id = models.UUIDField()
    dedupe_key = models.CharField(max_length=64, unique=True)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    channel = models.CharField(max_length=16)
    kind = models.CharField(max_length=32, blank=True, default="")
    state = models.CharField(max_length=16, default=DeliveryState.PENDING.value)
    attempts = models.PositiveSmallIntegerField(default=0)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    available_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        abstract = True
        indexes = [
            models.Index(
                fields=("state", "available_at"),
                name="%(app_label)s_%(class)s_rdy_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    state__in=(
                        DeliveryState.PENDING.value,
                        DeliveryState.LEASED.value,
                        DeliveryState.SENT.value,
                        DeliveryState.FAILED.value,
                        DeliveryState.SKIPPED.value,
                        DeliveryState.EXPIRED.value,
                    )
                ),
                name="%(app_label)s_%(class)s_state",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(state=DeliveryState.LEASED.value, lease_token__isnull=False, lease_until__isnull=False)
                    | (
                        ~models.Q(state=DeliveryState.LEASED.value)
                        & models.Q(lease_token__isnull=True, lease_until__isnull=True)
                    )
                ),
                name="%(app_label)s_%(class)s_lease",
            ),
        ]
