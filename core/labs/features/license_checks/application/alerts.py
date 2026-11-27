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
        action_path=notification.action_path,
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
        action_path="/lab-equipment/license",
    )
    transaction.on_commit(partial(_push, notification))
    return True


def send_missing_license_alerts(*, now=None) -> int:
    """Warn a check's owner once when a license the check expects is not found by any current run.

    A check is judged only once it has an applied ``ok`` run. When the license is found again, its
    alert record is removed, so a later disappearance warns again. Returns the warnings sent.
    """
    from django.db import IntegrityError

    from core.labs.models import LicenseAlert, LicenseAlertKind, LicenseCheckRun

    now = now or timezone.now()
    sent = 0
    checks = LicenseCheck.objects.filter(is_enabled=True, expected_licenses__isnull=False).distinct()
    for check in checks.prefetch_related("expected_licenses"):
        key = f"check:{check.pk}"
        if not LicenseCheckRun.objects.filter(license_check=check, status="ok", is_applied=True).exists():
            continue
        found = set(
            LicenseObservation.objects.filter(
                license_check=check, removed_at__isnull=True, license__isnull=False
            ).values_list("license_id", flat=True)
        )
        expected = [lic for lic in check.expected_licenses.all() if lic.deleted_at is None]
        LicenseAlert.objects.filter(
            kind=LicenseAlertKind.MISSING, key=key, license_id__in=[lic.pk for lic in expected if lic.pk in found]
        ).delete()
        recipient_id = check.creator_id or check.last_modified_by_id
        for license_record in expected:
            if license_record.pk in found or recipient_id is None:
                continue
            try:
                with transaction.atomic():
                    LicenseAlert.objects.create(license=license_record, kind=LicenseAlertKind.MISSING, key=key)
                    notification = Notification.objects.create(
                        message=f"License not found: {license_record.name or license_record.sku}"[:255],
                        details=f"The check '{check.name}' does not find it on any computer it runs on."[:255],
                        message_type=Notification.WARNING,
                        expiry_date=now + ALERT_LIFETIME,
                        target_user_id=recipient_id,
                        action_path="/lab-equipment/license",
                    )
                    transaction.on_commit(partial(_push, notification))
            except IntegrityError:
                continue
            sent += 1
    return sent
