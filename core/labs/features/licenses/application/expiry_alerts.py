"""Daily in-app warnings before a license expires (decision D4: 30 days ahead).

Each live license with an expiry date gets at most one warning per threshold and expiry date:
30 days ahead, 7 days ahead, and on expiry. A renewed license (new expiry date) starts again.
The recipient is the license owner, else whoever created it. Revoked and suspended licenses,
and licenses that expired more than a week ago, are left alone.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial

from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone

from core.labs.models import License, LicenseAlert, LicenseAlertKind, LicenseStatus, LicenseStatusRecord
from core.websocket.models import Notification
from core.websocket.publish_service import publish_user_notification

THRESHOLDS_DAYS = (30, 7, 0)
EXPIRED_LOOKBACK = timedelta(days=7)
ALERT_LIFETIME = timedelta(days=30)
_QUIET_STATUSES = (LicenseStatus.REVOKED, LicenseStatus.SUSPENDED)


@dataclass(frozen=True, slots=True)
class ExpiryAlertResult:
    checked: int
    sent: int


def _threshold(days_left: float) -> int:
    """The tightest threshold reached: 0 when expired, else 7 or 30."""
    return min(t for t in THRESHOLDS_DAYS if days_left <= t) if days_left > 0 else 0


def _push(notification: Notification) -> None:
    publish_user_notification(
        notification.target_user_id,
        notification.message,
        message_type=notification.message_type,
        details=notification.details or "",
        notification_id=notification.pk,
        action_path=notification.action_path,
    )


def _text(license_record: License, threshold: int, now: datetime) -> tuple[str, str]:
    name = license_record.name or license_record.sku
    when = timezone.localtime(license_record.expiry_date)
    if threshold == 0:
        return f"License expired: {name}", f"Expired {when:%Y-%m-%d %H:%M}. Renew or reactivate it."
    days = max(0, (license_record.expiry_date - now).days)
    return f"License expires in {days} days: {name}", f"Expires {when:%Y-%m-%d}. Plan the renewal."


def send_license_expiry_alerts(*, now: datetime | None = None) -> ExpiryAlertResult:
    now = now or timezone.now()
    latest_status = Subquery(
        LicenseStatusRecord.objects.filter(license=OuterRef("pk")).order_by("-created", "-id").values("status")[:1]
    )
    candidates = (
        License.objects.filter(
            deleted_at__isnull=True,
            expiry_date__isnull=False,
            expiry_date__lte=now + timedelta(days=max(THRESHOLDS_DAYS)),
            expiry_date__gte=now - EXPIRED_LOOKBACK,
        )
        .annotate(latest_status=latest_status)
        # A license with no status record yet counts as active (NOT IN would drop NULL).
        .filter(Q(latest_status__isnull=True) | ~Q(latest_status__in=_QUIET_STATUSES))
        .only("pk", "name", "sku", "expiry_date", "owner_id", "creator_id")
    )
    checked = sent = 0
    for license_record in candidates.iterator():
        checked += 1
        recipient_id = license_record.owner_id or license_record.creator_id
        if recipient_id is None:
            continue
        threshold = _threshold((license_record.expiry_date - now).total_seconds() / 86400)
        key = f"{threshold}d:{license_record.expiry_date.date().isoformat()}"
        try:
            with transaction.atomic():
                LicenseAlert.objects.create(license=license_record, kind=LicenseAlertKind.EXPIRY, key=key)
                message, details = _text(license_record, threshold, now)
                notification = Notification.objects.create(
                    message=message[:255],
                    details=details[:255],
                    message_type=Notification.ERROR if threshold == 0 else Notification.WARNING,
                    expiry_date=now + ALERT_LIFETIME,
                    target_user_id=recipient_id,
                    action_path="/lab-equipment/license",
                )
                transaction.on_commit(partial(_push, notification))
        except IntegrityError:
            continue  # already sent for this threshold and expiry date
        sent += 1
    return ExpiryAlertResult(checked, sent)


__all__ = ("ExpiryAlertResult", "send_license_expiry_alerts")
