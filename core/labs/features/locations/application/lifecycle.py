"""Lifecycle and access-policy changes of rooms and stations, and the deprecated ``change-status`` mapping.

Design: ``docs/proposals/resource-status-and-downtime.md``. The caller holds the resource row lock and
opens the transaction. Lifecycle history stays in the status records (``status`` holds the lifecycle
value; an access-policy change is recorded with ``metadata.access_policy``).
"""

from typing import Any

from django.core.exceptions import ValidationError

from core.labs.features.locations.exceptions import LocationConflict
from core.labs.models import (
    DowntimeReason,
    LegacyLocationStatus,
    ResourceAccessPolicy,
    ResourceCondition,
    ResourceDowntime,
    ResourceLifecycleStatus,
    Room,
    RoomStatusRecord,
    Station,
    StationStatusRecord,
)
from core.labs.models.resource.base.status import LIFECYCLE_TRANSITIONS, ensure_lifecycle_transition


def apply_lifecycle(
    resource: Room | Station,
    *,
    record_model: type[RoomStatusRecord] | type[StationStatusRecord],
    record_field: str,
    actor,
    lifecycle_status: str | None = None,
    access_policy: str | None = None,
    metadata: dict[str, Any] | None = None,
    has_active_children: bool = False,
):
    """Change lifecycle and/or access policy and append one history record. Idempotent: no change, no record.

    Retiring ends the current downtime window and cancels windows planned for later. ``has_active_children``
    (stations of a room, benches of a station that are not retired) refuses retirement.
    """
    metadata = {} if metadata is None else metadata
    if not isinstance(metadata, dict):
        raise ValidationError({"metadata": "Metadata must be an object."})
    if access_policy is not None and access_policy not in ResourceAccessPolicy.values:
        raise ValidationError({"access_policy": "Select open or restricted."})
    target = resource.lifecycle_status if lifecycle_status is None else lifecycle_status
    ensure_lifecycle_transition(current=resource.lifecycle_status, target=target)
    changed = []
    if target != resource.lifecycle_status:
        if target == ResourceLifecycleStatus.RETIRED:
            if has_active_children:
                raise LocationConflict("Retire or move what it contains before retiring it.")
            ResourceDowntime.objects.close_all(resource, actor=actor)
        resource.lifecycle_status = target
        changed.append("lifecycle_status")
    if access_policy is not None and access_policy != resource.access_policy:
        resource.access_policy = access_policy
        changed.append("access_policy")
        metadata = {**metadata, "access_policy": access_policy}
    if not changed:
        return None
    resource.save(actor=actor, update_fields=(*changed, "modified"))
    record = record_model(**{record_field: resource}, status=resource.lifecycle_status, metadata=metadata)
    record.full_clean()
    record.save(actor=actor)
    return record


def record_initial(
    resource: Room | Station,
    *,
    record_model: type[RoomStatusRecord] | type[StationStatusRecord],
    record_field: str,
    actor,
) -> None:
    record_model(**{record_field: resource}, status=resource.lifecycle_status).save(actor=actor)


def apply_legacy_status(
    resource: Room | Station,
    *,
    record_model: type[RoomStatusRecord] | type[StationStatusRecord],
    record_field: str,
    actor,
    status: str,
    metadata: dict[str, Any] | None = None,
    has_active_children: bool = False,
):
    """Map a deprecated seven-value ``status`` write onto lifecycle, access policy and downtime (RS3).

    Like the old endpoint, this does not check bookings (design rule 5). ``reserved`` is computed from
    bookings now, so it cannot be set.
    """
    legacy = LegacyLocationStatus
    metadata = {**({} if metadata is None else metadata), "legacy_status": status}
    common = {"record_model": record_model, "record_field": record_field, "actor": actor}
    if status == legacy.RESERVED:
        raise ValidationError({"status": "Reserved is computed from bookings and cannot be set."})
    if status == legacy.RETIRED:
        return _record_anyway(
            apply_lifecycle(
                resource,
                lifecycle_status=ResourceLifecycleStatus.RETIRED,
                metadata=metadata,
                has_active_children=has_active_children,
                **common,
            ),
            resource,
            metadata=metadata,
            **common,
        )
    if status == legacy.RESTRICTED:
        record = apply_lifecycle(resource, access_policy=ResourceAccessPolicy.RESTRICTED, metadata=metadata, **common)
        return _record_anyway(record, resource, metadata=metadata, **common)
    # Every other old value described a room or station that exists and is run by the lab.
    lifecycle = ResourceLifecycleStatus.IN_SERVICE
    access = ResourceAccessPolicy.OPEN if status == legacy.AVAILABLE else None
    record = apply_lifecycle(resource, lifecycle_status=lifecycle, access_policy=access, metadata=metadata, **common)
    if status == legacy.AVAILABLE:
        ResourceDowntime.objects.end_current(resource, actor=actor)
    else:
        condition, reason = {
            legacy.ISSUE: (ResourceCondition.OUT_OF_SERVICE, DowntimeReason.FAULT),
            legacy.CLOSED: (ResourceCondition.OUT_OF_SERVICE, DowntimeReason.OTHER),
            legacy.MAINTENANCE: (ResourceCondition.IN_MAINTENANCE, DowntimeReason.MAINTENANCE),
        }[legacy(status)]
        ResourceDowntime.objects.start_now(resource, condition=condition, reason=reason, actor=actor)
    return _record_anyway(record, resource, metadata=metadata, **common)


def _record_anyway(record, resource, *, record_model, record_field, actor, metadata):
    """The old endpoint always appended a record; keep that so its history shows every call."""
    if record is not None:
        return record
    record = record_model(**{record_field: resource}, status=resource.lifecycle_status, metadata=metadata)
    record.full_clean()
    record.save(actor=actor)
    return record


__all__ = [
    "LIFECYCLE_TRANSITIONS",
    "apply_legacy_status",
    "apply_lifecycle",
    "ensure_lifecycle_transition",
    "record_initial",
]
