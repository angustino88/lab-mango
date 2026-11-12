"""Application write commands for resource auditing by ID, SKU, and UID."""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import connection, transaction
from django.utils import timezone

from core.labs.features.resource_audit.exceptions import (
    AuditPermissionDeniedError,
    IdempotencyKeyReuseError,
    InvalidAuditResultError,
    InvalidIdempotencyKeyError,
    ResourceAuditNotFoundError,
    ResourceNotFoundError,
)
from core.labs.features.resource_audit.queries.selectors import resolve_resource
from core.labs.models.auditing.resource_audit import ResourceAudit
from core.labs.models.auditing.resource_change_log import ResourceChangeLog


@dataclass(frozen=True, slots=True)
class RecordResourceAuditInput:
    identifier: str | int
    identifier_type: str = "id"  # "id", "sku", or "uid"
    resource_type: str | None = None
    result: str = "PASS"
    remarks: str = ""
    audited_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RecordAuditByIdInput:
    resource_id: int | str
    resource_type: str | None = None
    result: str = "PASS"
    remarks: str = ""
    audited_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RecordAuditBySkuInput:
    sku: str
    resource_type: str | None = None
    result: str = "PASS"
    remarks: str = ""
    audited_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RecordAuditByUidInput:
    uid: str | uuid.UUID
    resource_type: str | None = None
    result: str = "PASS"
    remarks: str = ""
    audited_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RecordedAudit:
    """Result of an idempotent record: the audit and whether it was stored by an earlier request."""

    audit: ResourceAudit
    replayed: bool = False


MAX_IDEMPOTENCY_KEY_LENGTH = 128


@dataclass(frozen=True, slots=True)
class UpdateResourceAuditInput:
    audit_id: int
    result: str | None = None
    remarks: str | None = None
    audited_at: datetime | None = None


def _normalize_result(result_raw: str) -> str:
    cleaned = (result_raw or "").strip().upper()
    if cleaned in ("OK", "PASS", "PASSED"):
        return ResourceAudit.Result.PASS.value
    if cleaned in ("NOK", "FAIL", "FAILED"):
        return ResourceAudit.Result.FAIL.value
    if cleaned in ("NOT_ASSESSED", "NOT-ASSESSED", "NOT ASSESSED", "NONE", "PENDING"):
        return ResourceAudit.Result.NOT_ASSESSED.value
    valid_choices = [c[0] for c in ResourceAudit.Result.choices]
    if cleaned in valid_choices:
        return cleaned
    raise InvalidAuditResultError(
        f"Invalid audit result '{result_raw}'. Expected one of: PASS, FAIL, NOT_ASSESSED (or OK, NOK)."
    )


def _get_target_model(resource_type: str | None):
    if not resource_type:
        return None
    type_lower = resource_type.lower().strip()
    if type_lower in ("bench", "benches"):
        from core.labs.models.resource.bench.bench import Bench

        return Bench
    if type_lower in ("room", "rooms"):
        from core.labs.models.resource.location.room import Room

        return Room
    if type_lower in ("station", "stations"):
        from core.labs.models.resource.location.station import Station

        return Station
    if type_lower in ("license", "licenses"):
        from core.labs.models.resource.license.license import License

        return License
    if type_lower in ("equipment", "equipments"):
        from core.labs.models.resource.equipment.equipment import Equipment

        return Equipment
    ct = ContentType.objects.filter(app_label="labs", model=type_lower).first()
    if ct:
        return ct.model_class()
    raise ResourceNotFoundError(f"Unsupported resource type '{resource_type}'.")


@transaction.atomic
def record_resource_audit(command: RecordResourceAuditInput, *, actor: Any) -> ResourceAudit:
    """Record an audit entry for a lab resource identified by ID, SKU, or UID."""
    _ensure_authenticated(actor)
    return _create_audit(command, actor=actor)


def _ensure_authenticated(actor: Any) -> None:
    if not actor or not getattr(actor, "is_authenticated", False):
        raise AuditPermissionDeniedError("Authentication required to record a resource audit.")


def _create_audit(
    command: RecordResourceAuditInput,
    *,
    actor: Any,
    idempotency_key: str | None = None,
    request_hash: str = "",
) -> ResourceAudit:
    resource = resolve_resource(
        command.identifier,
        identifier_type=command.identifier_type,
        resource_type=command.resource_type,
    )
    norm_result = _normalize_result(command.result)
    audited_at = command.audited_at or timezone.now()

    if hasattr(resource, "record_audit"):
        audit = resource.record_audit(
            auditor=actor,
            result=norm_result,
            remarks=command.remarks,
            audited_at=audited_at,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
    else:
        audit = ResourceAudit.objects.create(
            resource=resource,
            auditor=actor,
            result=norm_result,
            remarks=command.remarks.strip(),
            audited_at=audited_at,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            creator=actor,
            last_modified_by=actor,
        )

    ResourceChangeLog.objects.create(
        resource=resource,
        action=ResourceChangeLog.Action.CREATE,
        field_name="audit",
        new_value={
            "audit_id": audit.id,
            "result": norm_result,
            "remarks": command.remarks,
            "audited_at": audited_at.isoformat(),
            "identifier_type": command.identifier_type,
            "identifier": str(command.identifier),
        },
        creator=actor,
        last_modified_by=actor,
    )

    return audit


def record_audit_by_id(command: RecordAuditByIdInput, *, actor: Any) -> ResourceAudit:
    """Record an audit for a resource identified by its database integer ID."""
    return record_resource_audit(
        RecordResourceAuditInput(
            identifier=command.resource_id,
            identifier_type="id",
            resource_type=command.resource_type,
            result=command.result,
            remarks=command.remarks,
            audited_at=command.audited_at,
        ),
        actor=actor,
    )


def record_audit_by_sku(command: RecordAuditBySkuInput, *, actor: Any) -> ResourceAudit:
    """Record an audit for a resource identified by its business SKU."""
    return record_resource_audit(
        RecordResourceAuditInput(
            identifier=command.sku,
            identifier_type="sku",
            resource_type=command.resource_type,
            result=command.result,
            remarks=command.remarks,
            audited_at=command.audited_at,
        ),
        actor=actor,
    )


def record_audit_by_uid(command: RecordAuditByUidInput, *, actor: Any) -> ResourceAudit:
    """Record an audit for a resource identified by its system UUID."""
    return record_resource_audit(
        RecordResourceAuditInput(
            identifier=str(command.uid),
            identifier_type="uid",
            resource_type=command.resource_type,
            result=command.result,
            remarks=command.remarks,
            audited_at=command.audited_at,
        ),
        actor=actor,
    )


def _request_hash(command: RecordAuditByUidInput) -> str:
    body = {
        "uid": str(command.uid),
        "resource_type": command.resource_type,
        "result": command.result,
        "remarks": command.remarks,
        "audited_at": command.audited_at.isoformat() if command.audited_at else None,
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _lock(key: str) -> None:
    number = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [number])


def record_audit_by_uid_once(
    command: RecordAuditByUidInput,
    *,
    actor: Any,
    idempotency_key: str,
) -> RecordedAudit:
    """Record an audit by UID at most once per (auditor, Idempotency-Key) (RW-6).

    Race guard: a transaction-scoped advisory lock on (auditor, key) serializes concurrent retries, and
    ``resource_audit_idempotency_uniq`` backs it in PostgreSQL. A repeat with the same body returns the
    stored audit; a repeat with a different body is refused with ``idempotency_key_reuse``.
    """
    _ensure_authenticated(actor)
    key = (idempotency_key or "").strip()
    if not key or len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise InvalidIdempotencyKeyError(f"Idempotency-Key must be 1 to {MAX_IDEMPOTENCY_KEY_LENGTH} characters.")
    request_hash = _request_hash(command)
    with transaction.atomic():
        _lock(f"resource-audit:{actor.pk}:{key}")
        existing = (
            ResourceAudit.objects.select_related("auditor", "resource_content_type")
            .filter(auditor=actor, idempotency_key=key)
            .first()
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise IdempotencyKeyReuseError("Idempotency-Key was already used with a different request.")
            return RecordedAudit(audit=existing, replayed=True)
        audit = _create_audit(
            RecordResourceAuditInput(
                identifier=str(command.uid),
                identifier_type="uid",
                resource_type=command.resource_type,
                result=command.result,
                remarks=command.remarks,
                audited_at=command.audited_at,
            ),
            actor=actor,
            idempotency_key=key,
            request_hash=request_hash,
        )
        return RecordedAudit(audit=audit)


@transaction.atomic
def update_resource_audit(command: UpdateResourceAuditInput, *, actor: Any) -> ResourceAudit:
    """Update fields on an existing audit record."""
    if not actor or not getattr(actor, "is_authenticated", False):
        raise AuditPermissionDeniedError("Authentication required to update an audit.")

    audit = (
        ResourceAudit.objects.select_related("auditor", "resource_content_type")
        .filter(pk=command.audit_id)
        .first()
    )
    if not audit:
        raise ResourceAuditNotFoundError(f"Resource audit with ID {command.audit_id} not found.")

    update_fields = ["last_modified_by"]
    audit.last_modified_by = actor

    old_state = {"result": audit.result, "remarks": audit.remarks}

    if command.result is not None:
        audit.result = _normalize_result(command.result)
        update_fields.append("result")

    if command.remarks is not None:
        audit.remarks = command.remarks.strip()
        update_fields.append("remarks")

    if command.audited_at is not None:
        audit.audited_at = command.audited_at
        update_fields.append("audited_at")

    audit.save(update_fields=update_fields)

    if audit.resource:
        ResourceChangeLog.objects.create(
            resource=audit.resource,
            action=ResourceChangeLog.Action.UPDATE,
            field_name="audit",
            old_value=old_state,
            new_value={"result": audit.result, "remarks": audit.remarks},
            creator=actor,
            last_modified_by=actor,
        )

    return audit


@transaction.atomic
def delete_resource_audit(audit_id: int, *, actor: Any) -> None:
    """Delete a resource audit record."""
    if not actor or not getattr(actor, "is_authenticated", False):
        raise AuditPermissionDeniedError("Authentication required to delete an audit.")

    audit = ResourceAudit.objects.filter(pk=audit_id).first()
    if not audit:
        raise ResourceAuditNotFoundError(f"Resource audit with ID {audit_id} not found.")

    res = audit.resource
    old_state = {"audit_id": audit.id, "result": audit.result, "remarks": audit.remarks}
    audit.delete()

    if res:
        ResourceChangeLog.objects.create(
            resource=res,
            action=ResourceChangeLog.Action.DELETE,
            field_name="audit",
            old_value=old_state,
            creator=actor,
            last_modified_by=actor,
        )
