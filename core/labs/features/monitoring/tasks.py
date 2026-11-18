"""Scheduled maintenance for device-observation history."""

from celery import shared_task

from core.labs.features.monitoring.application.retention import purge_device_observation_history


@shared_task(name="labs.monitoring.purge_device_observation_history")
def purge_device_observation_history_task() -> dict[str, int]:
    """Apply the receipt and detached-connection retention windows."""
    result = purge_device_observation_history()
    return {"batches_deleted": result.batches_deleted, "connections_deleted": result.connections_deleted}


__all__ = ("purge_device_observation_history_task",)
