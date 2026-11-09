from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models


class AgentReportedModel(models.Model):
    """Common identity and idempotency metadata for agent-submitted lab records."""

    agent_id = models.CharField(max_length=128)
    agent_version = models.CharField(max_length=64, blank=True, default="")
    event_id = models.UUIDField()
    reported_at = models.DateTimeField(
        help_text="Timestamp at which the agent emitted the report."
    )

    def clean(self) -> None:
        super().clean()
        self.agent_id = self.agent_id.strip()
        self.agent_version = self.agent_version.strip()

        if not self.agent_id:
            raise ValidationError({"agent_id": "Agent identity is required."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Agent reports are high-volume; relational and constraint integrity
        # is enforced by the database instead of per-field preflight queries.
        excluded_relations = [
            field.name for field in self._meta.concrete_fields if field.is_relation
        ]
        self.full_clean(
            exclude=excluded_relations,
            validate_unique=False,
            validate_constraints=False,
        )
        super().save(*args, **kwargs)

    class Meta:
        abstract = True
