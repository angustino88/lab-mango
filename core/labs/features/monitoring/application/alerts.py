"""In-app alerts when an expected device is observed disconnected.

Only a connected-to-disconnected transition of a matched device alerts, so repeated
snapshots of an already-disconnected device never notify twice. The notification row is
written in the reporting transaction; the websocket push runs after commit, so a rolled
back report never notifies and no network I/O happens under the reporting locks.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta
from functools import partial

from django.db import transaction
from django.utils import timezone

from core.labs.models.monitoring import ExpectedDevice
from core.websocket.models import Notification
from core.websocket.publish_service import publish_user_notification

ALERT_LIFETIME = timedelta(days=7)


def _push(notification: Notification) -> None:
    if notification.target_user_id is None:
        return
    publish_user_notification(
        notification.target_user_id,
        notification.message,
        message_type=notification.message_type,
        details=notification.details or "",
        notification_id=notification.pk,
        action_path=notification.action_path,
    )


def notify_expected_disconnects(*, computing_id: int, equipment_ids: Iterable[int], observed_at: datetime) -> int:
    """Notify each opted-in creator; return the number of notifications written."""
    equipment_ids = set(equipment_ids)
    if not equipment_ids:
        return 0
    expectations = ExpectedDevice.objects.filter(
        computing_id=computing_id,
        equipment_id__in=equipment_ids,
        notify_on_disconnect=True,
        creator__isnull=False,
    ).select_related("computing", "equipment")
    written = 0
    for expected in expectations:
        computing_name = expected.computing.name or expected.computing.sku
        equipment_name = expected.equipment.name or expected.equipment.sku
        notification = Notification.objects.create(
            message=f"{equipment_name} disconnected from {computing_name}"[:255],
            details=f"Observed {timezone.localtime(observed_at):%Y-%m-%d %H:%M}"[:255],
            message_type=Notification.WARNING,
            expiry_date=timezone.now() + ALERT_LIFETIME,
            target_user_id=expected.creator_id,
            action_path="/lab-monitoring",
        )
        transaction.on_commit(partial(_push, notification))
        written += 1
    return written


__all__ = ("notify_expected_disconnects",)
