"""Write commands for the monitoring event feature."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.monitoring.exceptions import ComputerNotFound, MonitoringEventConflict
from core.labs.models import MonitoringEvent, MonitoringEventAction
from core.labs.models.resource.equipment.equipment import Equipment


@dataclass(frozen=True)
class CreateMonitoringEventInput:
    computer_sku: str | None = None
    computer_id: int | None = None
    action: str = MonitoringEventAction.HEARTBEAT.value
    action_name: str = ""
    subject_type: str = ""
    subject_id: str = ""
    subject_name: str = ""
    payload: dict = field(default_factory=dict)
    occurred_at: datetime | None = None
    agent_id: str = "agent"
    agent_version: str = ""
    event_id: uuid.UUID | None = None


@transaction.atomic
def create_monitoring_event(
    command: CreateMonitoringEventInput,
    *,
    actor=None,
) -> MonitoringEvent:
    """Record an immutable monitoring event received from an agent."""
    computers = Equipment.objects.filter(computing_profile__isnull=False)
    computer = None
    if command.computer_id is not None:
        computer = computers.filter(pk=command.computer_id).first()
    elif command.computer_sku:
        computer = (
            computers.filter(sku=command.computer_sku).first()
            or computers.filter(name=command.computer_sku).first()
        )

    if not computer:
        raise ComputerNotFound("The specified computing equipment does not exist.")

    occurred_at = command.occurred_at or timezone.now()
    action = (
        command.action
        if command.action in MonitoringEventAction.values
        else MonitoringEventAction.CUSTOM
    )
    action_name = command.action_name or (command.action if action == MonitoringEventAction.CUSTOM else "")
    event_id = command.event_id or uuid.uuid4()

    event = MonitoringEvent(
        computer=computer,
        occurred_at=occurred_at,
        action=action,
        action_name=action_name,
        subject_type=command.subject_type,
        subject_id=command.subject_id,
        subject_name=command.subject_name,
        payload=command.payload,
        agent_id=command.agent_id,
        agent_version=command.agent_version,
        event_id=event_id,
        reported_at=timezone.now(),
    )
    try:
        event.full_clean()
        event.save()
    except (IntegrityError, ValidationError) as exc:
        if isinstance(exc, ValidationError) and "__all__" in getattr(exc, "message_dict", {}):
            raise MonitoringEventConflict(
                f"Monitoring event '{event_id}' for agent '{command.agent_id}' already recorded."
            ) from exc
        if isinstance(exc, IntegrityError):
            raise MonitoringEventConflict(
                f"Monitoring event '{event_id}' for agent '{command.agent_id}' already recorded."
            ) from exc
        raise

    return event


__all__ = [
    "CreateMonitoringEventInput",
    "create_monitoring_event",
]
