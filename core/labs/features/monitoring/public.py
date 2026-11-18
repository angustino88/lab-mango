"""Public API facade for the monitoring event feature."""

from .application import CreateMonitoringEventInput, create_monitoring_event
from .application.observe_devices import (
    MAX_DEVICES_PER_COLLECTOR,
    InvalidateDeviceConnectionsInput,
    invalidate_device_connections,
    observation_operation_scope,
    observe_devices,
)
from .application.retention import DeviceObservationPurgeResult, purge_device_observation_history
from .exceptions import (
    ComputerNotFound,
    MonitoringEventConflict,
    MonitoringEventNotFound,
    ObservationSnapshotRequired,
)
from .queries import get_monitoring_event, list_monitoring_events
from .queries.connections import FRESHNESS_WINDOW, connected_equipment_ids, list_device_connections
from .queries.expected import expected_device_watch_list

DEVICE_FRESHNESS_SECONDS = int(FRESHNESS_WINDOW.total_seconds())

__all__ = [
    "DEVICE_FRESHNESS_SECONDS",
    "MAX_DEVICES_PER_COLLECTOR",
    "InvalidateDeviceConnectionsInput",
    "observe_devices",
    "observation_operation_scope",
    "DeviceObservationPurgeResult",
    "purge_device_observation_history",
    "invalidate_device_connections",
    "list_device_connections",
    "connected_equipment_ids",
    "expected_device_watch_list",
    "ComputerNotFound",
    "ObservationSnapshotRequired",
    "CreateMonitoringEventInput",
    "MonitoringEventConflict",
    "MonitoringEventNotFound",
    "create_monitoring_event",
    "get_monitoring_event",
    "list_monitoring_events",
]
