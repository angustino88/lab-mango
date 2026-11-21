"""Create device-profile versions and approve them (lab admins only).

Race guards: rows of one profile key are locked before the next version number is chosen, backed by
`telemetry_profile_key_version_uniq`; approval locks the profile row. Idempotency: approving an approved
profile returns it unchanged.
"""

from dataclasses import dataclass, field
from typing import Any

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.text import slugify

from core.labs.models.telemetry import (
    DeviceProfile,
    DeviceProfileStatus,
    DeviceProtocol,
    MetricDefinition,
)
from core.labs.models.telemetry.reference_data import READ_MAP_VALIDATORS
from core.users.public import LabsPermission, has_permission

from .policies import ensure_can_approve_profiles
from .targets import raise_invalid

TEXT_LIMITS = {"manufacturer": 120, "model": 120, "notes": 4000}


@dataclass(frozen=True, slots=True)
class CreateDeviceProfileInput:
    key: str
    protocol: str
    read_map: dict[str, Any]
    manufacturer: str = ""
    model: str = ""
    comm_defaults: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ApproveDeviceProfileInput:
    profile_id: int


def _validate(command: CreateDeviceProfileInput, key: str) -> None:
    errors: dict[str, str] = {}
    if not key or len(key) > 64:
        errors["key"] = "Use 1-64 letters, digits, hyphens or underscores (e.g. chint_ddsu666)."
    if command.protocol not in DeviceProtocol.values:
        errors["protocol"] = f"Select one of: {', '.join(DeviceProtocol.values)}."
    else:
        errors.update(READ_MAP_VALIDATORS[command.protocol](command.read_map))
    if isinstance(command.read_map, dict) and command.read_map:
        known = set(
            MetricDefinition.objects.filter(key__in=command.read_map, is_active=True).values_list("key", flat=True)
        )
        for metric in sorted(set(command.read_map) - known):
            errors[f"read_map.{metric}"] = "Unknown or inactive metric."
    if not isinstance(command.comm_defaults, dict):
        errors["comm_defaults"] = "Must be an object."
    for name, limit in TEXT_LIMITS.items():
        if len(getattr(command, name) or "") > limit:
            errors[name] = f"Use at most {limit} characters."
    if errors:
        raise_invalid(errors)


@transaction.atomic
def create_device_profile(command: CreateDeviceProfileInput, *, actor) -> DeviceProfile:
    """A new draft version of a device profile (version 1 for a new key)."""
    key = slugify(command.key or "").replace("-", "_")
    _validate(command, key)
    list(DeviceProfile.objects.select_for_update().filter(key=key).values_list("pk", flat=True))
    latest = DeviceProfile.objects.filter(key=key).aggregate(latest=Max("version"))["latest"] or 0
    profile = DeviceProfile(
        key=key,
        version=latest + 1,
        protocol=command.protocol,
        manufacturer=command.manufacturer.strip(),
        model=command.model.strip(),
        read_map=command.read_map,
        comm_defaults=command.comm_defaults,
        notes=command.notes.strip(),
    )
    profile.save(actor=actor)
    return profile


@transaction.atomic
def approve_device_profile(command: ApproveDeviceProfileInput, *, actor) -> DeviceProfile:
    """Approve a draft after its bench test; channels may then use it."""
    may_approve = has_permission(actor, LabsPermission.TELEMETRY_PROFILE_APPROVE)
    ensure_can_approve_profiles(may_approve_profiles=may_approve)
    profile = DeviceProfile.objects.select_for_update().get(pk=command.profile_id)
    if profile.status == DeviceProfileStatus.APPROVED:
        return profile
    profile.status = DeviceProfileStatus.APPROVED
    profile.approved_at = timezone.now()
    profile.save(actor=actor, update_fields=["status", "approved_at", "modified"])
    return profile


__all__ = ["ApproveDeviceProfileInput", "CreateDeviceProfileInput", "approve_device_profile", "create_device_profile"]
