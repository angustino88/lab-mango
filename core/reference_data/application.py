"""Validated, atomic reference imports using explicit owner definitions.

Lock order: transaction advisory replay lock, resource import lock, then related
tables by label and rows by primary key. PostgreSQL uniqueness/FKs are final
guards against writers outside this API. No update/delete is exposed here.
"""

import hashlib
import json
from typing import Any

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, connection, models, transaction

from .contracts import CreateReferenceInput, ReferenceResource, ReferenceResult
from .exceptions import (
    IdempotencyKeyReuse,
    ReferenceAlreadyExists,
    ReferenceValidationFailed,
)
from .models import ReferenceImportReceipt
from .policies import ensure_access


def _lock(key: str) -> None:
    number = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [number])


def project_reference(resource: ReferenceResource, instance: Any) -> dict[str, Any]:
    """Explicit scalar and reference-ID projection; never serialize arbitrary model fields."""
    result = {"id": instance.pk}
    for name in resource.fields:
        field = instance._meta.get_field(name)
        if field.many_to_many:
            result[name] = sorted(row.pk for row in getattr(instance, name).all())
        elif field.many_to_one:
            result[f"{name}_id"] = getattr(instance, field.attname)
        else:
            result[name] = getattr(instance, name)
    return json.loads(json.dumps(result, cls=DjangoJSONEncoder))


def create_reference(resource: ReferenceResource, data: CreateReferenceInput, *, actor: Any) -> ReferenceResult:
    ensure_access(resource, actor, write=True)
    if not data.idempotency_key or len(data.idempotency_key) > 128:
        raise ReferenceValidationFailed("A non-empty Idempotency-Key of at most 128 characters is required.")
    allowed = {resource.model._meta.get_field(name).attname for name in resource.fields}
    if set(data.values) - allowed:
        raise ReferenceValidationFailed("Unknown or read-only fields.")
    encoded = json.dumps(data.values, cls=DjangoJSONEncoder, sort_keys=True, separators=(",", ":"))
    body_hash = hashlib.sha256(encoded.encode()).hexdigest()
    principal = f"user:{actor.pk}"
    with transaction.atomic():
        _lock(f"reference-replay:{principal}:{resource.key}:{data.idempotency_key}")
        receipt = ReferenceImportReceipt.objects.filter(
            principal=principal, operation=resource.key, key=data.idempotency_key
        ).first()
        if receipt is not None:
            if receipt.body_hash != body_hash:
                raise IdempotencyKeyReuse("Idempotency-Key was already used with different input.")
            return ReferenceResult(receipt.result, replayed=True)
        _lock(f"reference-create:{resource.model._meta.label_lower}")
        values = dict(data.values)
        many = {}
        for name in resource.fields:
            field = resource.model._meta.get_field(name)
            if field.many_to_many:
                many[name] = values.pop(name, [])
        instance = resource.model(**values)
        # Lock referenced rows before model.clean() checks parent state and membership.
        relations = []
        for field in instance._meta.fields:
            if field.many_to_one and field.name in resource.fields:
                pk = getattr(instance, field.attname)
                if pk is not None:
                    relations.append((field.remote_field.model, [pk]))
        for name, ids in many.items():
            relations.append((instance._meta.get_field(name).remote_field.model, ids))
        for model, ids in sorted(relations, key=lambda row: row[0]._meta.label_lower):
            rows = list(model.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
            if len(rows) != len(set(ids)):
                raise ReferenceValidationFailed("A referenced record does not exist.")
        try:
            if hasattr(instance, "normalize"):
                instance.normalize()
            identity = {name: getattr(instance, name) for name in resource.identity}
            if resource.model.objects.filter(**identity).exists():
                raise ReferenceAlreadyExists("A record with this identity already exists. Retrieve it instead.")
            instance.full_clean()
            with transaction.atomic():
                instance.save(actor=actor)
                for name, ids in many.items():
                    getattr(instance, name).set(ids)
        except ValidationError as error:
            raise ReferenceValidationFailed(
                "Reference data validation failed.",
                details=error.message_dict if hasattr(error, "message_dict") else {"non_field_errors": error.messages},
            ) from error
        except IntegrityError as error:
            diag = getattr(error.__cause__, "diag", None)
            constraint = getattr(diag, "constraint_name", None)
            known = {item.name for item in instance._meta.constraints if isinstance(item, models.UniqueConstraint)}
            known.update(
                f"{instance._meta.db_table}_{field.column}_key" for field in instance._meta.fields if field.unique
            )
            if constraint in known:
                raise ReferenceAlreadyExists("A record with this identity already exists.") from error
            raise
        result = project_reference(resource, instance)
        ReferenceImportReceipt.objects.create(
            principal=principal, operation=resource.key, key=data.idempotency_key, body_hash=body_hash, result=result
        )
        return ReferenceResult(result)
