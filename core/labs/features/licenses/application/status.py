"""License status transition command."""

from dataclasses import dataclass, field
from typing import Any

from django.db import transaction

from core.labs.features.licenses.exceptions import InvalidLicenseStatus
from core.labs.models import License, LicenseStatus, LicenseStatusRecord


@dataclass(frozen=True)
class ChangeLicenseStatusInput:
    license_id: int
    status: str
    details: dict[str, Any] = field(default_factory=dict)


@transaction.atomic
def change_license_status(command: ChangeLicenseStatusInput, *, actor):
    license_record = License.objects.select_for_update().get(
        id=command.license_id,
        deleted_at__isnull=True,
    )
    if command.status not in LicenseStatus.values:
        raise InvalidLicenseStatus(f"Unsupported license status: {command.status}.")
    metadata = command.details
    latest = license_record.status_records.order_by("-created", "-id").first()
    if latest and latest.status == command.status and latest.metadata == metadata:
        return latest
    record = LicenseStatusRecord(
        license=license_record,
        status=command.status,
        metadata=metadata,
        creator=actor,
        last_modified_by=actor,
    )
    record.save(actor=actor)
    return record


__all__ = ["ChangeLicenseStatusInput", "change_license_status"]
