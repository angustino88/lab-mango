"""Application write commands for laboratory analytics."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.labs.models import (
    AnalyticsSource,
    LaboratoryVisitEvent,
    StorageQuotaMeasurement,
)


@dataclass(frozen=True)
class RecordStorageQuotaInput:
    """Input parameters for capturing storage quota measurements."""

    account_identifier: str
    used_gibibytes: Decimal
    quota_gibibytes: Decimal
    computer_identifier: str = ""
    account_display_name: str = ""
    source: str = AnalyticsSource.COLLECTOR
    source_account_identifier: str = ""
    measured_at: datetime | None = None


@dataclass(frozen=True)
class RecordFacilityVisitInput:
    """Input parameters for recording a laboratory access visit event."""

    facility_identifier: str = ""
    occurred_at: datetime | None = None
    source: str = AnalyticsSource.APPLICATION
    external_reference: str = ""


@transaction.atomic
def record_storage_quota_measurement(
    input_data: RecordStorageQuotaInput,
    *,
    actor: Any = None,
) -> StorageQuotaMeasurement:
    """Record a point-in-time storage quota measurement."""
    measurement = StorageQuotaMeasurement.objects.create(
        measured_at=input_data.measured_at or timezone.now(),
        account_identifier=input_data.account_identifier,
        account_display_name=input_data.account_display_name,
        computer_identifier=input_data.computer_identifier,
        used_gibibytes=input_data.used_gibibytes,
        quota_gibibytes=input_data.quota_gibibytes,
        source=input_data.source or AnalyticsSource.COLLECTOR,
        source_account_identifier=input_data.source_account_identifier,
    )
    return measurement


@transaction.atomic
def record_facility_visit(
    input_data: RecordFacilityVisitInput,
    *,
    actor: Any = None,
) -> LaboratoryVisitEvent:
    """Record a physical or remote laboratory access visit event."""
    visitor = actor if getattr(actor, "is_authenticated", False) else None
    event = LaboratoryVisitEvent.objects.create(
        occurred_at=input_data.occurred_at or timezone.now(),
        source=input_data.source or AnalyticsSource.APPLICATION,
        external_reference=input_data.external_reference or "",
        visitor=visitor,
        facility_identifier=input_data.facility_identifier or "",
    )
    return event


__all__ = [
    "RecordFacilityVisitInput",
    "RecordStorageQuotaInput",
    "record_facility_visit",
    "record_storage_quota_measurement",
]
