"""Read queries and selectors for resource audits by ID, SKU, and UID."""

import uuid
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q, QuerySet

from core.labs.features.resource_audit.exceptions import ResourceNotFoundError
from core.labs.models.auditing.resource_audit import ResourceAudit


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


def get_resource_audit(audit_id: int) -> ResourceAudit | None:
    """Retrieve an audit by primary key."""
    return (
        ResourceAudit.objects.select_related("auditor", "resource_content_type")
        .filter(pk=audit_id)
        .first()
    )


def _downcast_equipment(equipment: models.Model | None) -> models.Model | None:
    """Equipment is one table since redesign step 6; there is no subtype to resolve."""
    return equipment




def resolve_resource(
    identifier: int | str | uuid.UUID,
    *,
    identifier_type: str = "id",
    resource_type: str | None = None,
) -> models.Model:
    """Resolve a target lab resource by ID, SKU, or UID."""
    from core.labs.models.resource.bench.bench import Bench
    from core.labs.models.resource.equipment.equipment import Equipment
    from core.labs.models.resource.license.license import License
    from core.labs.models.resource.location.room import Room
    from core.labs.models.resource.location.station import Station

    id_type = identifier_type.lower().strip()
    target_model = _get_target_model(resource_type)

    if id_type == "id":
        try:
            pk_val = int(identifier)
        except (ValueError, TypeError) as err:
            raise ResourceNotFoundError(f"Invalid integer ID: '{identifier}'") from err

        if target_model:
            res = target_model.objects.filter(pk=pk_val, deleted_at__isnull=True).first()
        else:
            raw_eq = Equipment.objects.filter(pk=pk_val, deleted_at__isnull=True).first()
            if raw_eq:
                res = _downcast_equipment(raw_eq) or raw_eq
            else:
                res = (
                    Bench.objects.filter(pk=pk_val, deleted_at__isnull=True).first()
                    or License.objects.filter(pk=pk_val, deleted_at__isnull=True).first()
                    or Room.objects.filter(pk=pk_val, deleted_at__isnull=True).first()
                    or Station.objects.filter(pk=pk_val, deleted_at__isnull=True).first()
                )

    elif id_type == "sku":
        sku_str = str(identifier).strip()
        if target_model:
            res = target_model.objects.filter(
                Q(sku=sku_str) | Q(name=sku_str),
                deleted_at__isnull=True,
            ).first()
        else:
            raw_eq = Equipment.objects.filter(sku=sku_str, deleted_at__isnull=True).first()
            if raw_eq:
                res = _downcast_equipment(raw_eq) or raw_eq
            else:
                res = (
                    Bench.objects.filter(sku=sku_str, deleted_at__isnull=True).first()
                    or License.objects.filter(sku=sku_str, deleted_at__isnull=True).first()
                    or Room.objects.filter(Q(sku=sku_str) | Q(name=sku_str), deleted_at__isnull=True).first()
                    or Station.objects.filter(Q(sku=sku_str) | Q(name=sku_str), deleted_at__isnull=True).first()
                )

    elif id_type == "uid":
        try:
            uid_val = uuid.UUID(str(identifier))
        except (ValueError, TypeError, AttributeError) as err:
            raise ResourceNotFoundError(f"Invalid UUID: '{identifier}'") from err

        if target_model:
            res = target_model.objects.filter(uid=uid_val, deleted_at__isnull=True).first()
        else:
            raw_eq = Equipment.objects.filter(uid=uid_val, deleted_at__isnull=True).first()
            if raw_eq:
                res = _downcast_equipment(raw_eq) or raw_eq
            else:
                res = (
                    Bench.objects.filter(uid=uid_val, deleted_at__isnull=True).first()
                    or License.objects.filter(uid=uid_val, deleted_at__isnull=True).first()
                    or Room.objects.filter(uid=uid_val, deleted_at__isnull=True).first()
                    or Station.objects.filter(uid=uid_val, deleted_at__isnull=True).first()
                )
    else:
        raise ResourceNotFoundError(f"Unsupported identifier type '{identifier_type}'. Expected: 'id', 'sku', or 'uid'.")

    if not res:
        raise ResourceNotFoundError(f"Resource with {id_type.upper()} '{identifier}' not found.")

    return _downcast_equipment(res) or res




def list_audits_for_resource(
    identifier: int | str | uuid.UUID,
    *,
    identifier_type: str = "id",
    resource_type: str | None = None,
    result: str | None = None,
) -> QuerySet[ResourceAudit]:
    """List historical audits for a resource resolved by ID, SKU, or UID."""
    resource = resolve_resource(
        identifier,
        identifier_type=identifier_type,
        resource_type=resource_type,
    )
    content_types = [ContentType.objects.get_for_model(resource, for_concrete_model=False)]

    qs = ResourceAudit.objects.filter(
        resource_content_type__in=content_types,
        resource_object_id=str(resource.pk),
    ).select_related("auditor", "resource_content_type").prefetch_related("resource")

    if result:
        qs = qs.filter(result=result.upper())
    return qs.order_by("-audited_at", "-id")


def list_audits_by_id(
    resource_id: int | str,
    *,
    resource_type: str | None = None,
    result: str | None = None,
) -> QuerySet[ResourceAudit]:
    """List audits for a resource identified by integer ID."""
    return list_audits_for_resource(
        resource_id,
        identifier_type="id",
        resource_type=resource_type,
        result=result,
    )


def list_audits_by_sku(
    sku: str,
    *,
    resource_type: str | None = None,
    result: str | None = None,
) -> QuerySet[ResourceAudit]:
    """List audits for a resource identified by business SKU."""
    return list_audits_for_resource(
        sku,
        identifier_type="sku",
        resource_type=resource_type,
        result=result,
    )


def list_audits_by_uid(
    uid: str | uuid.UUID,
    *,
    resource_type: str | None = None,
    result: str | None = None,
) -> QuerySet[ResourceAudit]:
    """List audits for a resource identified by system UUID."""
    return list_audits_for_resource(
        uid,
        identifier_type="uid",
        resource_type=resource_type,
        result=result,
    )


def get_latest_audit_by_resource(
    identifier: int | str | uuid.UUID,
    *,
    identifier_type: str = "id",
    resource_type: str | None = None,
) -> ResourceAudit | None:
    """Retrieve latest audit for a resource resolved by ID, SKU, or UID."""
    return list_audits_for_resource(
        identifier,
        identifier_type=identifier_type,
        resource_type=resource_type,
    ).first()


def list_all_resource_audits(
    *,
    resource_type: str | None = None,
    result: str | None = None,
    auditor_id: int | None = None,
    search: str | None = None,
) -> QuerySet[ResourceAudit]:
    """List resource audits globally with optional filtering."""
    qs = ResourceAudit.objects.select_related("auditor", "resource_content_type").prefetch_related("resource").all()

    if resource_type:
        type_lower = resource_type.lower().strip()
        ct = ContentType.objects.filter(app_label="labs", model=type_lower).first()
        if ct:
            qs = qs.filter(resource_content_type=ct)

    if result:
        qs = qs.filter(result=result.upper())

    if auditor_id:
        qs = qs.filter(auditor_id=auditor_id)

    if search:
        qs = qs.filter(Q(remarks__icontains=search) | Q(auditor__username__icontains=search))

    return qs.order_by("-audited_at", "-id")


def get_audit_result_options() -> list[dict[str, Any]]:
    """Return flat options array strictly conforming to system /options standard."""
    return [
        {"id": 1, "sku": ResourceAudit.Result.PASS.value, "name": ResourceAudit.Result.PASS.label},
        {"id": 2, "sku": ResourceAudit.Result.FAIL.value, "name": ResourceAudit.Result.FAIL.label},
        {
            "id": 3,
            "sku": ResourceAudit.Result.NOT_ASSESSED.value,
            "name": ResourceAudit.Result.NOT_ASSESSED.label,
        },
    ]
