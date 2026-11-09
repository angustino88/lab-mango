"""License agreement creation command."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction

from core.labs.models import License, LicenseAgreement


@dataclass(frozen=True)
class CreateLicenseAgreementInput:
    license_id: int
    price: Decimal
    currency: str
    billing_period: str
    valid_from: date
    valid_until: date | None = None


@transaction.atomic
def create_license_agreement(command: CreateLicenseAgreementInput, *, actor) -> LicenseAgreement:
    license_record = License.objects.select_for_update().get(
        id=command.license_id,
        deleted_at__isnull=True,
    )
    agreement = LicenseAgreement(
        license=license_record,
        price=command.price,
        currency=command.currency,
        billing_period=command.billing_period,
        valid_from=command.valid_from,
        valid_until=command.valid_until,
        creator=actor,
        last_modified_by=actor,
    )
    agreement.save(actor=actor)
    return agreement


__all__ = ["CreateLicenseAgreementInput", "create_license_agreement"]
