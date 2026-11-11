"""Application commands for the live activity state of computing equipment.

``ComputingActivity`` is a mutable 1:1 projection that is separate from the equipment lifecycle
status history and from booking status. Status-change notifications are emitted by the model
signal after commit, so these commands only persist state.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from core.labs.models import ComputingActivity, ComputingActivityStatus, Equipment

_WRITABLE_FIELDS = frozenset(
    {
        "status",
        "remote_user",
        "remote_user_display_name",
        "remote_computer",
        "remote_ip",
        "booking_code",
    }
)


@dataclass(frozen=True, slots=True)
class SyncComputingActivityInput:
    """Reported activity state. ``fields`` holds only the values the caller supplied."""

    computing_id: int
    fields: tuple[tuple[str, object], ...]


def ensure_computing_activity(computing: Equipment) -> ComputingActivity:
    """Return the activity row for ``computing``, creating a before-transition row when missing."""
    # The offline timestamp constraint is checked immediately, so persist an initial
    # offline timestamp for new rows; API transitions away from offline still clear it.
    activity, _ = ComputingActivity.objects.get_or_create(
        computing=computing,
        defaults={"status": ComputingActivityStatus.OFFLINE, "offline_at": timezone.now()},
    )
    return activity


def _apply_transition_timestamps(activity: ComputingActivity, previous_status: str, now: datetime) -> None:
    """Maintain inactive timestamps and the inactivity reminder counter."""
    if activity.status == previous_status:
        return
    if activity.status == ComputingActivityStatus.INACTIVE:
        activity.inactive_at = now
    elif previous_status == ComputingActivityStatus.INACTIVE:
        activity.inactive_at = None
        activity.inactive_reminder_count = 0


def _apply_initial_offline_timestamp(activity: ComputingActivity, previous_status: str, now: datetime) -> None:
    """Stamp incoming offline transitions and clear the timestamp when leaving offline."""
    if activity.status == ComputingActivityStatus.OFFLINE and previous_status != ComputingActivityStatus.OFFLINE:
        activity.offline_at = now
    elif activity.status != ComputingActivityStatus.OFFLINE and previous_status == ComputingActivityStatus.OFFLINE:
        activity.offline_at = None


@transaction.atomic
def sync_computing_activity(command: SyncComputingActivityInput, *, actor=None) -> ComputingActivity:
    """Lock and update the live activity of one computing equipment record.

    ``actor`` is ``None`` for agent (API-key) submissions. Only these submissions
    refresh ``last_agent_report_at``; coordinator edits never change the heartbeat.
    Raises ``Equipment.DoesNotExist``
    for a missing or soft-deleted computer (a unit without a computing profile) and ``ValidationError`` for unknown fields or statuses.
    """
    values = dict(command.fields)
    unexpected = values.keys() - _WRITABLE_FIELDS
    if unexpected:
        raise ValidationError({name: "Unknown or read-only field." for name in sorted(unexpected)})
    if "status" in values and values["status"] not in ComputingActivityStatus.values:
        raise ValidationError({"status": "Select a valid status."})

    computing = Equipment.objects.get(
        pk=command.computing_id, deleted_at__isnull=True, computing_profile__isnull=False
    )
    ensure_computing_activity(computing)
    activity = ComputingActivity.objects.select_for_update().get(computing=computing)
    previous_status = activity.status

    for name, value in values.items():
        setattr(activity, name, value)
    now = timezone.now()
    # Repeat inactive reports refresh the agent heartbeat but retain the original
    # inactive timestamp and reminder count; coordinator status edits are transitions only.
    if "status" in values:
        _apply_initial_offline_timestamp(activity, previous_status, now)
    _apply_transition_timestamps(activity, previous_status, now)
    if actor is None:
        activity.last_agent_report_at = now
    activity.full_clean()
    activity.save()
    _publish_activity_change_on_commit(activity, previous_status)
    return activity

def _publish_activity_change_on_commit(activity, previous_status):
    from django.db import transaction
    if activity.status == previous_status:
        return

    computer_id = activity.computing_id
    status = activity.status

    def _do_publish():
        from core.labs.models.resource.equipment.assignment import EquipmentAssignment
        from core.websocket.publish_service import (
            publish_computing_activity_update,
            publish_dashboard_status_update,
            publish_monitoring_update,
        )
        bench_id = (
            EquipmentAssignment.objects.filter(
                equipment_id=computer_id,
                unassigned_at__isnull=True,
            )
            .values_list("bench_id", flat=True)
            .first()
        )
        payload = {
            "computer_id": computer_id,
            "status": status,
            "previous_status": previous_status,
            "bench_id": bench_id,
        }
        publish_computing_activity_update(computing_id=computer_id, data=payload)
        if bench_id is not None:
            publish_monitoring_update(
                bench_id=bench_id,
                event_type="computer_status_change",
                data=payload,
            )
        publish_dashboard_status_update(
            event_type="computer_status_change",
            data=payload,
        )

    transaction.on_commit(_do_publish)



@transaction.atomic
def mark_stale_computing_activities_offline(*, now: datetime | None = None) -> int:
    """Mark non-offline agent-reported activities offline after a strict 10-minute timeout.

    Rows without an agent heartbeat are deliberately excluded: they may represent
    coordinator-only or legacy state, not an agent whose liveness is known. A sweep
    may serialize with an in-flight report; the report's later heartbeat refresh
    makes the row eligible only after a future cutoff passes.
    """
    current_time = now or timezone.now()
    cutoff = current_time - timedelta(minutes=10)
    stale_activities: QuerySet[ComputingActivity] = ComputingActivity.objects.filter(
        last_agent_report_at__lt=cutoff,
    ).exclude(status=ComputingActivityStatus.OFFLINE)
    updated = 0
    for activity in stale_activities.select_for_update().order_by("pk"):
        previous_status = activity.status
        activity.status = ComputingActivityStatus.OFFLINE
        activity.offline_at = current_time
        activity.save(update_fields=("status", "offline_at", "modified"))
        _publish_activity_change_on_commit(activity, previous_status)
        updated += 1
    return updated


__all__ = (
    "SyncComputingActivityInput",
    "ensure_computing_activity",
    "mark_stale_computing_activities_offline",
    "sync_computing_activity",
)
