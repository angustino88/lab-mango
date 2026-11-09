"""Scheduled maintenance for computing activity heartbeats."""

from celery import shared_task

from core.labs.features.equipment.categories.computing.application import mark_stale_computing_activities_offline


@shared_task(name="labs.equipment.computing.mark_stale_activities_offline")
def mark_stale_computing_activities_offline_task() -> int:
    """Apply the agent heartbeat timeout to stale computing activity rows."""
    return mark_stale_computing_activities_offline()


__all__ = ("mark_stale_computing_activities_offline_task",)
