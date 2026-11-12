"""Equipment-owned reference catalog and selector reads (ADR 002)."""

from typing import Any

from django.db.models import CharField, Exists, F, OuterRef, Q, QuerySet, Value

from core.labs.models.resource.base.resource import Department, ResourceGroup
from core.labs.models.resource.equipment.reference_data import (
    EquipmentCategory,
    EquipmentKind,
    EquipmentManufacturer,
    EquipmentProductModel,
    EquipmentType,
)
from core.reference_data.contracts import ReferenceResource
from core.reference_data.exceptions import ReferencePermissionDenied
from core.reference_data.public import get_reference, list_references
from core.users.public import LabsRole, has_labs_role

# Organisation lookups other screens use; every other equipment reference list is visible to
# coordinators and administrators only (owner decisions R4, R9).
OPEN_REFERENCE_MODELS = frozenset({"department", "resourcegroup"})


def _ensure_can_read(resource: ReferenceResource, actor: Any) -> None:
    if resource.model._meta.model_name in OPEN_REFERENCE_MODELS:
        return
    if not has_labs_role(actor, LabsRole.COORDINATOR):
        raise ReferencePermissionDenied()


def list_catalog_references(resource: ReferenceResource, *, actor: Any, filters: dict[str, Any]) -> QuerySet:
    _ensure_can_read(resource, actor)
    return list_references(resource, actor=actor, filters=filters)


def get_catalog_reference(resource: ReferenceResource, *, actor: Any, reference_id: int) -> Any:
    _ensure_can_read(resource, actor)
    return get_reference(resource, actor=actor, reference_id=reference_id)


# 1. EquipmentCategory
def list_equipment_categories(*, search: str | None = None) -> QuerySet[EquipmentCategory]:
    qs = EquipmentCategory.objects.all().order_by("name", "pk")
    if search:
        qs = qs.filter(name__icontains=search)
    return qs


def get_equipment_category(*, category_id: int) -> EquipmentCategory:
    return EquipmentCategory.objects.get(pk=category_id)


def list_equipment_category_options(*, actor: Any = None, q: str | None = None, include_ids: list[int] | None = None) -> QuerySet:
    cond = Q(active=True)
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        EquipmentCategory.objects.filter(cond)
        .annotate(sku=F("key"))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


# 2. EquipmentKind
def list_equipment_kinds(*, search: str | None = None, category_id: int | None = None) -> QuerySet[EquipmentKind]:
    qs = EquipmentKind.objects.select_related("category").order_by("name", "pk")
    if category_id is not None:
        qs = qs.filter(category_id=category_id)
    if search:
        qs = qs.filter(name__icontains=search)
    return qs


def get_equipment_kind(*, kind_id: int) -> EquipmentKind:
    return EquipmentKind.objects.select_related("category").get(pk=kind_id)


def list_equipment_kind_options(
    *, actor: Any = None, q: str | None = None, category_id: int | None = None, include_ids: list[int] | None = None
) -> QuerySet:
    cond = Q(active=True)
    if category_id is not None:
        cond &= Q(category_id=category_id)
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        EquipmentKind.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


# 3. EquipmentType
def list_equipment_types(
    *, search: str | None = None, kind_id: int | None = None, category_id: int | None = None
) -> QuerySet[EquipmentType]:
    qs = EquipmentType.objects.select_related("kind", "kind__category").order_by("name", "pk")
    if kind_id is not None:
        qs = qs.filter(kind_id=kind_id)
    if category_id is not None:
        qs = qs.filter(kind__category_id=category_id)
    if search:
        qs = qs.filter(name__icontains=search)
    return qs


def get_equipment_type(*, type_id: int) -> EquipmentType:
    return EquipmentType.objects.select_related("kind", "kind__category").get(pk=type_id)


def list_equipment_type_options(
    *,
    actor: Any = None,
    q: str | None = None,
    kind_id: int | None = None,
    category_id: int | None = None,
    include_ids: list[int] | None = None,
) -> QuerySet:
    cond = Q(active=True)
    if kind_id is not None:
        cond &= Q(kind_id=kind_id)
    if category_id is not None:
        cond &= Q(kind__category_id=category_id)
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        EquipmentType.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


# 4. EquipmentManufacturer
def list_equipment_manufacturers(*, search: str | None = None, category_id: int | None = None) -> QuerySet[EquipmentManufacturer]:
    qs = EquipmentManufacturer.objects.all().order_by("name", "pk")
    if category_id is not None:
        cat_matches = EquipmentCategory.objects.filter(manufacturers=OuterRef("pk"), pk=category_id)
        qs = qs.filter(Exists(cat_matches))
    if search:
        qs = qs.filter(name__icontains=search)
    return qs


def get_equipment_manufacturer(*, manufacturer_id: int) -> EquipmentManufacturer:
    return EquipmentManufacturer.objects.get(pk=manufacturer_id)


def list_equipment_manufacturer_options(
    *, actor: Any = None, q: str | None = None, category_id: int | None = None, include_ids: list[int] | None = None
) -> QuerySet:
    cond = Q(active=True)
    if category_id is not None:
        cat_matches = EquipmentCategory.objects.filter(manufacturers=OuterRef("pk"), pk=category_id)
        cond &= Exists(cat_matches)
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        EquipmentManufacturer.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


# 5. EquipmentProductModel
def list_equipment_product_models(
    *, search: str | None = None, manufacturer_id: int | None = None, type_id: int | None = None
) -> QuerySet[EquipmentProductModel]:
    qs = EquipmentProductModel.objects.select_related("manufacturer", "equipment_type").order_by("name", "pk")
    if manufacturer_id is not None:
        qs = qs.filter(manufacturer_id=manufacturer_id)
    if type_id is not None:
        qs = qs.filter(equipment_type_id=type_id)
    if search:
        qs = qs.filter(name__icontains=search)
    return qs


def get_equipment_product_model(*, model_id: int) -> EquipmentProductModel:
    return EquipmentProductModel.objects.select_related("manufacturer", "equipment_type").get(pk=model_id)


def list_equipment_product_model_options(
    *,
    actor: Any = None,
    q: str | None = None,
    manufacturer_id: int | None = None,
    type_id: int | None = None,
    include_ids: list[int] | None = None,
) -> QuerySet:
    cond = Q(active=True)
    if manufacturer_id is not None:
        cond &= Q(manufacturer_id=manufacturer_id)
    if type_id is not None:
        cond &= Q(equipment_type_id=type_id)
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        EquipmentProductModel.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


# 6. Department
def list_departments(*, search: str | None = None) -> QuerySet[Department]:
    qs = Department.objects.all().order_by("name", "pk")
    if search:
        qs = qs.filter(name__icontains=search)
    return qs


def get_department(*, department_id: int) -> Department:
    return Department.objects.get(pk=department_id)


def list_department_options(*, actor: Any = None, q: str | None = None, include_ids: list[int] | None = None) -> QuerySet:
    cond = Q(active=True)
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        Department.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


# 7. ResourceGroup
def list_resource_groups(*, search: str | None = None, department_id: int | None = None) -> QuerySet[ResourceGroup]:
    qs = ResourceGroup.objects.select_related("department").order_by("name", "pk")
    if department_id is not None:
        qs = qs.filter(department_id=department_id)
    if search:
        qs = qs.filter(name__icontains=search)
    return qs


def get_resource_group(*, group_id: int) -> ResourceGroup:
    return ResourceGroup.objects.select_related("department").get(pk=group_id)


def list_resource_group_options(
    *, actor: Any = None, q: str | None = None, department_id: int | None = None, include_ids: list[int] | None = None
) -> QuerySet:
    cond = Q(active=True)
    if department_id is not None:
        cond &= Q(department_id=department_id)
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        ResourceGroup.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )
