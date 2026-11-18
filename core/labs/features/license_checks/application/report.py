"""Intake of one license-check run from an agent, matching and inventory effects (proposal 5.4).

Per run, in one transaction:

1. The check must be enabled and target the reporting computer ``C`` (derived from the signing
   identity), otherwise ``NotFound``. Exact retries (same ``Idempotency-Key`` and content) return
   the first acknowledgment; the same key with other content is a conflict.
2. A run with an older ``sequence`` is ``stale`` and a run of an older ``revision`` is
   ``outdated_revision``: both are recorded only. A run whose status is not ``ok`` is ``recorded``:
   the licenses found earlier stay as they are.
3. An applied ``ok`` run replaces the check's license set on ``C``: each license is matched by its
   serial to ``License.serial_number`` and its carrier must be at ``C`` and hold the license
   (decision D8). Licenses no longer listed get ``removed_at``.
4. A ``matched`` license is compared with the inventory (decision D1): a different expiry or
   maximum version is written, with a change-log entry naming the agent; a past expiry records the
   ``expired`` status (never over ``revoked`` or ``suspended``), and a renewed one ends an
   ``expired`` status this feature recorded.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from core.common.db.idempotency import try_claim_operation
from core.common.domain.errors import Conflict, NotFound
from core.labs.features.equipment.public import lock_monitoring_computing, match_hardware_ids, normalize_hardware_id
from core.labs.features.licenses.public import (
    ChangeLicenseStatusInput,
    UpdateLicenseInput,
    change_license_status,
    update_license,
)
from core.labs.features.monitoring.public import connected_equipment_ids
from core.labs.models import (
    Equipment,
    EquipmentAssignment,
    License,
    LicenseAssignment,
    LicenseCheck,
    LicenseCheckRun,
    LicenseCheckRunStatus,
    LicenseObservation,
    LicenseObservationStatus,
    LicenseStatus,
    ResourceChangeLog,
)

from ..contracts import LicenseCheckRunAcknowledgment, LicenseCheckRunInput, ReportedLicense
from ..queries.checks import checks_for_computer

SOURCE = "license_check"
_KEEP_STATUSES = frozenset({LicenseStatus.REVOKED, LicenseStatus.SUSPENDED})


def run_operation_scope(command: LicenseCheckRunInput) -> bytes:
    return f"POST:/agent/license-checks/{command.check_key}:{command.computing_id}:{command.idempotency_key}".encode()


def content_hash(command: LicenseCheckRunInput) -> str:
    body = asdict(command)
    for name in ("computing_id", "agent_uid", "idempotency_key"):
        body.pop(name)
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def _ack(run: LicenseCheckRun, result: str, *, replayed: bool = False) -> LicenseCheckRunAcknowledgment:
    return LicenseCheckRunAcknowledgment(run.idempotency_key, run.sequence, result, run.received_at, replayed)


def _result_of(run: LicenseCheckRun, check: LicenseCheck) -> str:
    if run.is_applied:
        return "applied" if run.status == LicenseCheckRunStatus.OK else "recorded"
    return "outdated_revision" if run.revision != check.revision else "stale"


class _Placement:
    """What is at the reporting computer: itself, its bench neighbours and connected devices."""

    def __init__(self, computing_id: int):
        self.computing_id = computing_id
        self._units: set[int] | None = None

    @property
    def units(self) -> set[int]:
        if self._units is None:
            benches = EquipmentAssignment.objects.filter(
                equipment_id=self.computing_id, unassigned_at__isnull=True, bench__isnull=False
            ).values("bench_id")
            on_bench = EquipmentAssignment.objects.filter(
                bench_id__in=benches, unassigned_at__isnull=True, equipment__deleted_at__isnull=True
            ).values_list("equipment_id", flat=True)
            self._units = {self.computing_id, *on_bench, *connected_equipment_ids(computing_id=self.computing_id)}
        return self._units


def _carrier_unit(reported: ReportedLicense, check: LicenseCheck, computing_id: int) -> int | None:
    kind = reported.carrier_type
    if kind in ("computer", "server"):
        return computing_id
    if kind == "equipment":
        uid = reported.carrier_equipment_uid or check.carrier.get("equipment_uid", "")
        return (
            Equipment.objects.filter(uid=uid, deleted_at__isnull=True).values_list("pk", flat=True).first()
            if uid
            else None
        )
    if kind in ("device", "dongle") and reported.carrier_hardware_kind and reported.carrier_hardware_value:
        pair = (reported.carrier_hardware_kind, reported.carrier_hardware_value)
        match = match_hardware_ids(computing_id=computing_id, evidence=[((pair,), "")])[((pair,), "")]
        return match.equipment_id if match.status == "matched" else None
    return None


def _find_license(reported: ReportedLicense, carrier_id: int | None, computing_id: int) -> tuple[str, License | None]:
    """``(status, license)`` with status ``matched`` (candidate found), ``unregistered`` or ``ambiguous``."""
    live = License.objects.filter(deleted_at__isnull=True)
    if reported.license_serial:
        candidates = list(live.filter(serial_number__iexact=reported.license_serial).select_related("vendor")[:10])
        if len(candidates) > 1 and reported.vendor:
            candidates = [c for c in candidates if c.vendor.name.casefold() == reported.vendor.casefold()]
    else:
        # Tools without a license ID: the one license of this product assigned to the carrier or computer.
        holders = {computing_id} | ({carrier_id} if carrier_id else set())
        candidates = list(
            live.filter(
                product__name__iexact=reported.product_name,
                equipment_assignments__equipment_id__in=holders,
                equipment_assignments__unassigned_at__isnull=True,
            ).distinct()[:10]
        )
    if not candidates:
        return LicenseObservationStatus.UNREGISTERED, None
    if len(candidates) > 1:
        return LicenseObservationStatus.AMBIGUOUS, None
    return LicenseObservationStatus.MATCHED, candidates[0]


def _evaluate(
    reported: ReportedLicense, check: LicenseCheck, placement: _Placement
) -> tuple[str, License | None, int | None]:
    computing_id = placement.computing_id
    carrier_id = _carrier_unit(reported, check, computing_id)
    status, license_record = _find_license(reported, carrier_id, computing_id)
    if license_record is None:
        return status, None, carrier_id
    if carrier_id is None:
        return LicenseObservationStatus.CARRIER_UNLINKED, license_record, None
    if carrier_id not in placement.units:
        return LicenseObservationStatus.CARRIER_NOT_AT_COMPUTER, license_record, carrier_id
    holders = set(
        LicenseAssignment.objects.filter(license=license_record, unassigned_at__isnull=True).values_list(
            "equipment_id", flat=True
        )
    )
    if holders & {carrier_id, computing_id}:
        return LicenseObservationStatus.MATCHED, license_record, carrier_id
    if holders:
        return LicenseObservationStatus.CARRIER_MISMATCH, license_record, carrier_id
    return LicenseObservationStatus.UNASSIGNED, license_record, carrier_id


def _log(license_record: License, field: str, old, new, metadata: dict) -> None:
    ResourceChangeLog(
        resource_content_type=ContentType.objects.get_for_model(License, for_concrete_model=False),
        resource_object_id=str(license_record.pk),
        action=ResourceChangeLog.Action.UPDATE,
        field_name=field,
        old_value=old.isoformat() if hasattr(old, "isoformat") else old,
        new_value=new.isoformat() if hasattr(new, "isoformat") else new,
        metadata=metadata,
    ).save(actor=None)


def _apply_effects(license_record: License, reported: ReportedLicense, metadata: dict) -> None:
    changes = {}
    if reported.expires_at != license_record.expiry_date:
        changes["expiry_date"] = reported.expires_at
    if reported.max_version and reported.max_version != license_record.max_version:
        changes["max_version"] = reported.max_version
    if changes:
        old = {name: getattr(license_record, name) for name in changes}
        update_license(UpdateLicenseInput(license_record.pk, changes), actor=None)
        for name, value in changes.items():
            _log(license_record, name, old[name], value, metadata)
    latest = license_record.status_records.order_by("-created", "-id").first()
    latest_status = latest.status if latest else None
    expired = reported.expires_at is not None and reported.expires_at <= timezone.now()
    details = {"source": SOURCE, **metadata}
    if expired and latest_status not in _KEEP_STATUSES and latest_status != LicenseStatus.EXPIRED:
        change_license_status(ChangeLicenseStatusInput(license_record.pk, LicenseStatus.EXPIRED, details), actor=None)
    elif not expired and latest_status == LicenseStatus.EXPIRED and (latest.metadata or {}).get("source") == SOURCE:
        in_use = license_record.equipment_assignments.filter(unassigned_at__isnull=True).exists()
        target = LicenseStatus.ASSIGNED if in_use else LicenseStatus.AVAILABLE
        change_license_status(ChangeLicenseStatusInput(license_record.pk, target, details), actor=None)


def _apply_run(run: LicenseCheckRun, check: LicenseCheck, command: LicenseCheckRunInput) -> None:
    now = run.received_at
    placement = _Placement(command.computing_id)
    existing = {
        o.observation_key: o
        for o in LicenseObservation.objects.select_for_update().filter(
            license_check=check, computing_id=command.computing_id
        )
    }
    seen = set()
    for reported in command.licenses:
        if reported.observation_key in seen:
            continue
        seen.add(reported.observation_key)
        status, license_record, carrier_id = _evaluate(reported, check, placement)
        values = {
            "vendor": reported.vendor,
            "product_code": reported.product_code,
            "product_name": reported.product_name,
            "license_serial": reported.license_serial,
            "carrier_type": reported.carrier_type,
            "carrier_hardware_kind": reported.carrier_hardware_kind,
            "carrier_hardware_value": reported.carrier_hardware_value,
            "carrier_equipment_id": carrier_id,
            "license": license_record,
            "status": status,
            "expires_at": reported.expires_at,
            "final_expires_at": reported.final_expires_at,
            "max_version": reported.max_version,
            "is_reactivatable": reported.is_reactivatable,
            "last_run": run,
            "last_seen_at": now,
            "removed_at": None,
        }
        observation = existing.get(reported.observation_key)
        if observation is None:
            LicenseObservation.objects.create(
                license_check=check,
                computing_id=command.computing_id,
                observation_key=reported.observation_key,
                first_seen_at=now,
                **values,
            )
        else:
            for name, value in values.items():
                setattr(observation, name, value)
            observation.save()
        if status == LicenseObservationStatus.MATCHED and license_record is not None:
            metadata = {
                "check_key": check.key,
                "computing_id": command.computing_id,
                "agent_uid": str(command.agent_uid),
                "observation_key": reported.observation_key,
            }
            _apply_effects(License.objects.get(pk=license_record.pk), reported, metadata)
    gone = [key for key, o in existing.items() if key not in seen and o.removed_at is None]
    if gone:
        LicenseObservation.objects.filter(
            license_check=check, computing_id=command.computing_id, observation_key__in=gone
        ).update(removed_at=now, last_run=run)


@transaction.atomic
def report_license_check_run(command: LicenseCheckRunInput) -> LicenseCheckRunAcknowledgment:
    if not try_claim_operation(run_operation_scope(command)):
        raise Conflict("This request is still running.", code="request_in_progress")
    lock_monitoring_computing(command.computing_id)
    check = checks_for_computer(computing_id=command.computing_id).filter(key=command.check_key).first()
    if check is None:
        raise NotFound("No enabled license check with this key runs on this computer.")
    digest = content_hash(command)
    replay = LicenseCheckRun.objects.filter(
        computing_id=command.computing_id, license_check=check, idempotency_key=command.idempotency_key
    ).first()
    if replay is not None:
        if replay.content_hash != digest:
            raise Conflict("This Idempotency-Key was used for another run.", code="idempotency_key_reused")
        return _ack(replay, _result_of(replay, check), replayed=True)
    newest = (
        LicenseCheckRun.objects.filter(license_check=check, computing_id=command.computing_id)
        .order_by("-sequence")
        .values_list("sequence", flat=True)
        .first()
    )
    is_current = command.revision == check.revision and (newest is None or command.sequence > newest)
    run = LicenseCheckRun.objects.create(
        license_check=check,
        computing_id=command.computing_id,
        agent_uid=command.agent_uid,
        idempotency_key=command.idempotency_key,
        content_hash=digest,
        revision=command.revision,
        sequence=command.sequence,
        status=command.status,
        error_code=command.error_code[:64],
        error_message=command.error_message[:512],
        started_at=command.started_at,
        duration_ms=command.duration_ms,
        license_count=len(command.licenses),
        is_applied=is_current,
        received_at=timezone.now(),
    )
    if is_current and command.status == LicenseCheckRunStatus.OK:
        _apply_run(run, check, command)
    return _ack(run, _result_of(run, check))


def normalized_carrier_value(kind: str, value: str) -> str:
    return normalize_hardware_id(kind, value) if kind else value.strip()
