"""Commands that create, change and delete license inventory records.

Race guard: every change locks the license row (``select_for_update``) inside one transaction.
Assignment commands lock the same row first, so the seat and assignment counts read here cannot
change underneath a write. SKU uniqueness among live licenses is a PostgreSQL constraint of
``ResourceModel``; a collision surfaces as ``LicenseConflict``.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from core.labs.features.licenses.exceptions import LicenseConflict
from core.labs.models import Department, Group, License
from core.labs.models.resource.license.license import (
    LicenseCategory,
    LicenseProduct,
    LicenseRestriction,
    LicenseType,
    LicenseVendor,
)

# Fields an update may change. ``sku`` is fixed at creation.
UPDATABLE_FIELDS = frozenset(
    {
        "name",
        "department_id",
        "group_id",
        "owner_id",
        "remark",
        "product_id",
        "vendor_id",
        "type_id",
        "category_id",
        "restriction_id",
        "seats",
        "max_version",
        "identifier",
        "expiry_date",
    }
)
# Reference field -> model. A missing target is a field error, not a server error.
_REFERENCES = {
    "department_id": Department,
    "group_id": Group,
    "product_id": LicenseProduct,
    "vendor_id": LicenseVendor,
    "type_id": LicenseType,
    "category_id": LicenseCategory,
    "restriction_id": LicenseRestriction,
}
_REQUIRED_REFERENCES = frozenset({"product_id", "vendor_id", "type_id", "category_id"})


@dataclass(frozen=True)
class CreateLicenseInput:
    sku: str
    product_id: int
    vendor_id: int
    type_id: int
    category_id: int
    name: str = ""
    department_id: int | None = None
    group_id: int | None = None
    owner_id: int | None = None
    remark: str = ""
    restriction_id: int | None = None
    seats: int = 1
    max_version: str = ""
    # The license key is a secret: kept out of ``repr`` so it never reaches a log line.
    identifier: str = field(default="", repr=False)
    expiry_date: datetime | None = None


@dataclass(frozen=True)
class UpdateLicenseInput:
    license_id: int
    # Only the keys the caller sent; may carry ``identifier``, so it stays out of ``repr``.
    changes: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class DeleteLicenseInput:
    license_id: int


def _command(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            with transaction.atomic():
                return function(*args, **kwargs)
        except (IntegrityError, ProtectedError) as exc:
            raise LicenseConflict("The write conflicts with an existing license or reference.") from exc

    return wrapped


def _check_references(data: Mapping[str, Any]) -> None:
    errors: dict[str, str] = {}
    for name, model in _REFERENCES.items():
        if name not in data:
            continue
        value = data[name]
        if value is None:
            if name in _REQUIRED_REFERENCES:
                errors[name] = "This field may not be null."
        elif not model._default_manager.filter(pk=value).exists():
            errors[name] = "The referenced record does not exist."
    owner_id = data.get("owner_id")
    if owner_id is not None and not get_user_model()._default_manager.filter(pk=owner_id).exists():
        errors["owner_id"] = "The referenced user does not exist."
    if errors:
        raise ValidationError(errors)


@_command
def create_license(command: CreateLicenseInput, *, actor) -> License:
    values = {name: getattr(command, name) for name in command.__dataclass_fields__}
    _check_references(values)
    license_record = License(**values)
    license_record.save(actor=actor)
    return license_record


@_command
def update_license(command: UpdateLicenseInput, *, actor) -> License:
    unknown = set(command.changes) - UPDATABLE_FIELDS
    if unknown:
        raise ValidationError({name: "Unknown or read-only field." for name in sorted(unknown)})
    license_record = License.objects.select_for_update().get(pk=command.license_id, deleted_at__isnull=True)
    _check_references(command.changes)
    seats = command.changes.get("seats")
    if seats is not None:
        in_use = license_record.equipment_assignments.filter(unassigned_at__isnull=True).count()
        if seats < in_use:
            raise LicenseConflict(f"{in_use} seats are in use; the license cannot have fewer seats.")
    for name, value in command.changes.items():
        setattr(license_record, name, value)
    license_record.save(actor=actor)
    return license_record


@_command
def delete_license(command: DeleteLicenseInput, *, actor) -> None:
    license_record = License.objects.select_for_update().get(pk=command.license_id, deleted_at__isnull=True)
    if license_record.equipment_assignments.filter(unassigned_at__isnull=True).exists():
        raise LicenseConflict("Unassign the license from its equipment before deleting it.")
    license_record.soft_delete(actor=actor)


__all__ = [
    "CreateLicenseInput",
    "DeleteLicenseInput",
    "UpdateLicenseInput",
    "create_license",
    "delete_license",
    "update_license",
]
