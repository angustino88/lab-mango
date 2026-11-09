from django.core.exceptions import ValidationError
from django.db import models
from model_utils.models import TimeStampedModel

from core.labs.models.base import AgentReportedModel


class MonitoringEventAction(models.TextChoices):
    HEARTBEAT = "heartbeat", "Heartbeat"
    DEVICE_INSERTED = "device_inserted", "Device inserted"
    DEVICE_REMOVED = "device_removed", "Device removed"
    DEVICE_CHANGED = "device_changed", "Device changed"
    DEVICE_STATUS_CHANGED = "device_status_changed", "Device status changed"
    INVENTORY_SNAPSHOT = "inventory_snapshot", "Inventory snapshot"
    METRIC_REPORTED = "metric_reported", "Metric reported"
    ALERT_RAISED = "alert_raised", "Alert raised"
    ALERT_RESOLVED = "alert_resolved", "Alert resolved"
    CUSTOM = "custom", "Custom"


class MonitoringEvent(AgentReportedModel, TimeStampedModel):
    """Immutable event received from one monitored computer agent."""

    computer = models.ForeignKey(
        "labs.ComputingEquipment",
        related_name="monitoring_events",
        on_delete=models.PROTECT,
    )
    occurred_at = models.DateTimeField()
    action = models.CharField(max_length=64, choices=MonitoringEventAction.choices)
    action_name = models.CharField(max_length=128, blank=True, default="")
    subject_type = models.CharField(max_length=128, blank=True, default="")
    subject_id = models.CharField(max_length=255, blank=True, default="")
    subject_name = models.CharField(max_length=255, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)

    def clean(self):
        super().clean()
        self.action_name = self.action_name.strip()
        self.subject_type = self.subject_type.strip()
        self.subject_id = self.subject_id.strip()
        self.subject_name = self.subject_name.strip()

        if self.action == MonitoringEventAction.CUSTOM and not self.action_name:
            raise ValidationError({"action_name": "A custom action requires an action name."})
        if not isinstance(self.payload, dict):
            raise ValidationError({"payload": "Event payload must be a JSON object."})

    def __str__(self):
        action = self.action_name or self.action
        return f"{self.computer}: {action} ({self.event_id})"

    @property
    def event_type(self) -> str:
        return self.action

    @event_type.setter
    def event_type(self, value: str) -> None:
        self.action = value

    @property
    def source(self) -> str:
        return self.agent_id or (self.payload.get("source", "agent") if isinstance(self.payload, dict) else "agent")

    @source.setter
    def source(self, value: str) -> None:
        self.agent_id = value

    @property
    def category(self) -> str:
        return self.subject_type

    @category.setter
    def category(self, value: str) -> None:
        self.subject_type = value

    @property
    def object_name(self) -> str:
        return self.subject_name

    @object_name.setter
    def object_name(self, value: str) -> None:
        self.subject_name = value

    @property
    def details(self):
        return self.payload

    @details.setter
    def details(self, value):
        self.payload = value

    @property
    def computer_name(self) -> str:
        if self.computer_id and hasattr(self, "computer") and self.computer:
            return self.computer.name
        return ""

    @property
    def technical_user(self) -> str:
        if isinstance(self.payload, dict) and "technical_user" in self.payload:
            return str(self.payload["technical_user"])
        if (
            self.computer_id
            and hasattr(self, "computer")
            and self.computer
            and getattr(self.computer, "technical_user", None)
        ):
            return self.computer.technical_user.username
        return ""

    @property
    def remote_user(self) -> str:
        if isinstance(self.payload, dict):
            return str(self.payload.get("remote_user", ""))
        return ""

    @property
    def remote_user_displayname(self) -> str:
        if isinstance(self.payload, dict):
            return str(self.payload.get("remote_user_displayname", self.payload.get("remote_user_display_name", "")))
        return ""

    @property
    def bench(self):
        if not self.computer_id:
            return None
        from core.labs.models.resource.equipment.assignment import EquipmentAssignment
        assignment = (
            EquipmentAssignment.objects.filter(
                equipment_id=self.computer_id,
                unassigned_at__isnull=True,
            )
            .select_related("bench")
            .first()
        )
        return assignment.bench if assignment else None

    @property
    def details_str(self) -> str:
        if isinstance(self.payload, dict):
            parts = [f"{k}: {v}" for k, v in self.payload.items()]
            return "; ".join(parts)
        if isinstance(self.payload, list):
            return "; ".join(str(item) for item in self.payload)
        return str(self.payload or "")

    class Meta:
        app_label = "labs"
        ordering = ("-occurred_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("computer", "agent_id", "event_id"),
                name="unique_monitoring_event_per_agent",
            ),
        ]
        indexes = [
            models.Index(fields=("computer", "-occurred_at"), name="monitor_computer_time_idx"),
            models.Index(fields=("action", "-occurred_at"), name="monitor_action_time_idx"),
            models.Index(fields=("subject_type", "subject_id", "-occurred_at"), name="monitor_subject_time_idx"),
        ]

