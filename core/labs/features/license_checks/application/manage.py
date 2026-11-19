"""Commands that configure license checks (decision D7).

Admins create and delete checks and change what agents run (probe, extraction, carrier, vendor).
Coordinators may change the name, interval, targets and whether the check is enabled. Every change
an agent must pick up increases ``revision``; runs of an older revision then no longer apply.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from django.db import IntegrityError, transaction

from core.common.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed
from core.labs.models import (
    Bench,
    Equipment,
    EquipmentCategory,
    License,
    LicenseCheck,
    LicenseCheckTarget,
    Room,
    Station,
)
from core.users.public import LabsRole, has_labs_role

from ..config import validate_configuration
from ..presets import PRESETS

TARGET_MODELS = {
    "room": Room,
    "station": Station,
    "bench": Bench,
    "category": EquipmentCategory,
    "equipment": Equipment,
}
MAX_TARGETS = 200
ADMIN_FIELDS = frozenset({"vendor", "probe", "extract", "carrier"})
COORDINATOR_FIELDS = frozenset(
    {"name", "interval_minutes", "is_enabled", "is_lab_wide", "targets", "expected_license_ids"}
)
MAX_EXPECTED_LICENSES = 200
# Fields the agent receives: a change must reach it as a new revision.
AGENT_FIELDS = frozenset({"name", "vendor", "interval_minutes", "probe", "extract", "carrier"})


@dataclass(frozen=True)
class CheckTarget:
    kind: str  # room | station | bench | category | equipment
    id: int


@dataclass(frozen=True)
class CreateLicenseCheckInput:
    key: str
    name: str
    probe: Mapping[str, Any]
    extract: Mapping[str, Any]
    carrier: Mapping[str, Any]
    vendor: str = ""
    interval_minutes: int = 360
    is_enabled: bool = True
    is_lab_wide: bool = False
    targets: Sequence[CheckTarget] = ()
    preset_key: str = ""
    expected_license_ids: Sequence[int] = ()


@dataclass(frozen=True)
class CreateLicenseCheckFromPresetInput:
    preset_key: str
    key: str = ""
    name: str = ""
    is_enabled: bool = True
    is_lab_wide: bool = False
    targets: Sequence[CheckTarget] = ()
    expected_license_ids: Sequence[int] = ()


@dataclass(frozen=True)
class UpdateLicenseCheckInput:
    check_id: int
    changes: Mapping[str, Any] = field(default_factory=dict)


def _require_admin(actor) -> None:
    if not has_labs_role(actor, LabsRole.ADMIN):
        raise Forbidden("Only Labs administrators may change what agents run.", code="license_check_admin_only")


def _check_equipment_carrier(carrier: Mapping[str, Any]) -> None:
    uid = carrier.get("equipment_uid")
    if uid and not Equipment.objects.filter(uid=uid, deleted_at__isnull=True).exists():
        message = "No active equipment has this UID."
        raise ValidationFailed(message, details={"carrier.equipment_uid": message})


def _clean_targets(targets: Sequence[CheckTarget]) -> list[CheckTarget]:
    unique = list(dict.fromkeys(targets))
    if len(unique) > MAX_TARGETS:
        message = f"At most {MAX_TARGETS} targets."
        raise ValidationFailed(message, details={"targets": message})
    for target in unique:
        model = TARGET_MODELS.get(target.kind)
        if model is None:
            message = f"Use one of: {', '.join(TARGET_MODELS)}."
            raise ValidationFailed(message, details={"targets": message})
        live = model._default_manager.filter(pk=target.id)
        if hasattr(model, "deleted_at"):
            live = live.filter(deleted_at__isnull=True)
        if not live.exists():
            message = f"{target.kind} {target.id} does not exist."
            raise ValidationFailed(message, details={"targets": message})
    return unique


def _set_expected_licenses(check: LicenseCheck, license_ids: Sequence[int]) -> None:
    """Licenses the check should find (not sent to agents, so no new revision)."""
    ids = list(dict.fromkeys(license_ids))
    if len(ids) > MAX_EXPECTED_LICENSES:
        message = f"At most {MAX_EXPECTED_LICENSES} expected licenses."
        raise ValidationFailed(message, details={"expected_license_ids": message})
    found = set(License.objects.filter(pk__in=ids, deleted_at__isnull=True).values_list("pk", flat=True))
    if missing := [i for i in ids if i not in found]:
        message = f"Licenses not found: {', '.join(map(str, missing))}."
        raise ValidationFailed(message, details={"expected_license_ids": message})
    check.expected_licenses.set(ids)


def _replace_targets(check: LicenseCheck, targets: list[CheckTarget]) -> None:
    check.targets.all().delete()
    LicenseCheckTarget.objects.bulk_create(
        LicenseCheckTarget(license_check=check, **{f"{target.kind}_id": target.id}) for target in targets
    )


@transaction.atomic
def create_license_check(command: CreateLicenseCheckInput, *, actor) -> LicenseCheck:
    _require_admin(actor)
    probe, extract, carrier = validate_configuration(command.probe, command.extract, command.carrier)
    _check_equipment_carrier(carrier)
    targets = _clean_targets(command.targets)
    check = LicenseCheck(
        key=command.key.strip(),
        name=command.name.strip(),
        vendor=command.vendor.strip(),
        probe=probe,
        extract=extract,
        carrier=carrier,
        interval_minutes=command.interval_minutes,
        is_enabled=command.is_enabled,
        is_lab_wide=command.is_lab_wide,
        preset_key=command.preset_key,
    )
    check.full_clean(exclude=["creator", "last_modified_by"], validate_unique=False, validate_constraints=False)
    try:
        with transaction.atomic():
            check.save(actor=actor)
    except IntegrityError:
        raise Conflict("A license check with this key exists.", code="license_check_key_exists") from None
    _replace_targets(check, targets)
    _set_expected_licenses(check, command.expected_license_ids)
    return check


def create_license_check_from_preset(command: CreateLicenseCheckFromPresetInput, *, actor) -> LicenseCheck:
    preset = PRESETS.get(command.preset_key)
    if preset is None:
        raise NotFound("Preset not found.")
    return create_license_check(
        CreateLicenseCheckInput(
            key=command.key or preset["key"],
            name=command.name or preset["name"],
            vendor=preset["vendor"],
            probe=preset["probe"],
            extract=preset["extract"],
            carrier=preset["carrier"],
            interval_minutes=preset["interval_minutes"],
            is_enabled=command.is_enabled,
            is_lab_wide=command.is_lab_wide,
            targets=command.targets,
            preset_key=preset["key"],
            expected_license_ids=command.expected_license_ids,
        ),
        actor=actor,
    )


@transaction.atomic
def update_license_check(command: UpdateLicenseCheckInput, *, actor) -> LicenseCheck:
    changes = dict(command.changes)
    unknown = set(changes) - ADMIN_FIELDS - COORDINATOR_FIELDS
    if unknown:
        raise ValidationFailed("Unknown or read-only field.", details={name: "Read-only." for name in sorted(unknown)})
    check = LicenseCheck.objects.select_for_update().filter(pk=command.check_id).first()
    if check is None:
        raise NotFound("License check not found.")
    if set(changes) & ADMIN_FIELDS:
        _require_admin(actor)
        probe, extract, carrier = validate_configuration(
            changes.get("probe", check.probe),
            changes.get("extract", check.extract),
            changes.get("carrier", check.carrier),
        )
        _check_equipment_carrier(carrier)
        changes.update(probe=probe, extract=extract, carrier=carrier)
    expected_license_ids = changes.pop("expected_license_ids", None)
    if expected_license_ids is not None:
        _set_expected_licenses(check, expected_license_ids)
    targets = changes.pop("targets", None)
    if targets is not None:
        _replace_targets(check, _clean_targets(targets))
    changed = {name for name, value in changes.items() if getattr(check, name) != value}
    for name in changed:
        setattr(check, name, value := changes[name])
        if name in {"name", "vendor"} and isinstance(value, str):
            setattr(check, name, value.strip())
    if changed & AGENT_FIELDS:
        check.revision += 1
    if changed:
        check.full_clean(exclude=["creator", "last_modified_by"], validate_unique=False, validate_constraints=False)
        check.save(actor=actor)
    return check


@transaction.atomic
def delete_license_check(*, check_id: int, actor) -> None:
    _require_admin(actor)
    deleted, _ = LicenseCheck.objects.filter(pk=check_id).delete()
    if not deleted:
        raise NotFound("License check not found.")
