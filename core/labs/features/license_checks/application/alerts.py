"""In-app alerts when a license an agent found needs a coordinator.

One notification when an observation first needs attention or its reason changes (for example
"not in inventory" → "carrier not at this computer"); repeated runs with the same outcome, and
matched licenses, never notify. The recipient is the check's owner (its creator, else whoever
changed it last). The row is written in the reporting transaction and pushed after commit.
"""

from datetime import timedelta
from functools import partial

from django.db import transaction
from django.utils import timezone

from core.labs.models import LicenseCheck, LicenseObservation, LicenseObservationStatus
from core.websocket.models import Notification
from core.websocket.publish_service import publish_user_notification

ALERT_LIFETIME = timedelta(days=14)


def _push(notification: Notification) -> None:
    publish_user_notification(
        notification.target_user_id,
        notification.message,
        message_type=notification.message_type,
        details=notification.details or "",
        notification_id=notification.pk,
    )


def needs_alert(observation: LicenseObservation, previous_status: str | None) -> bool:
    """New, reappeared or changed reason, and not matched."""
    return observation.status != LicenseObservationStatus.MATCHED and observation.status != previous_status


def notify_license_attention(check: LicenseCheck, observation: LicenseObservation, computing_name: str) -> bool:
    recipient_id = check.creator_id or check.last_modified_by_id
    if recipient_id is None:
        return False
    serial = f" ({observation.license_serial})" if observation.license_serial else ""
    notification = Notification.objects.create(
        message=f"License needs attention: {observation.product_name}{serial} on {computing_name}"[:255],
        details=f"{observation.get_status_display()} · Licenses → Found on lab hardware"[:255],
        message_type=Notification.WARNING,
        expiry_date=timezone.now() + ALERT_LIFETIME,
        target_user_id=recipient_id,
    )
    transaction.on_commit(partial(_push, notification))
    return True
