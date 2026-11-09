"""License-owned lookup queries (ADR 002)."""

from typing import Any

from django.db.models import CharField, Q, QuerySet, Value

from core.labs.models.resource.license.license import (
    LicenseCategory,
    LicenseProduct,
    LicenseRestriction,
    LicenseType,
    LicenseVendor,
)
from core.reference_data.contracts import ReferenceResource
from core.reference_data.public import get_reference, list_references


def list_catalog_references(resource: ReferenceResource, *, actor: Any, filters: dict[str, Any]) -> QuerySet:
    return list_references(resource, actor=actor, filters=filters)


def get_catalog_reference(resource: ReferenceResource, *, actor: Any, reference_id: int) -> Any:
    return get_reference(resource, actor=actor, reference_id=reference_id)


# Vendors
def list_license_vendors(*, search: str | None = None) -> QuerySet[LicenseVendor]:
    qs = LicenseVendor.objects.all().order_by("name", "pk")
    if search:
        qs = qs.filter(name__icontains=search)
    return qs


def get_license_vendor(*, vendor_id: int) -> LicenseVendor:
    return LicenseVendor.objects.get(pk=vendor_id)


def list_license_vendor_options(*, actor: Any = None, q: str | None = None, include_ids: list[int] | None = None) -> QuerySet:
    cond = Q()
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        LicenseVendor.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


# Products
def list_license_products(*, search: str | None = None, vendor_id: int | None = None) -> QuerySet[LicenseProduct]:
    qs = LicenseProduct.objects.select_related("vendor").order_by("name", "pk")
    if vendor_id is not None:
        qs = qs.filter(vendor_id=vendor_id)
    if search:
        qs = qs.filter(name__icontains=search)
    return qs


def get_license_product(*, product_id: int) -> LicenseProduct:
    return LicenseProduct.objects.select_related("vendor").get(pk=product_id)


def list_license_product_options(
    *, actor: Any = None, q: str | None = None, vendor_id: int | None = None, include_ids: list[int] | None = None
) -> QuerySet:
    cond = Q()
    if vendor_id is not None:
        cond &= Q(vendor_id=vendor_id)
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        LicenseProduct.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


# Types
def list_license_types(*, search: str | None = None) -> QuerySet[LicenseType]:
    qs = LicenseType.objects.all().order_by("name", "pk")
    if search:
        qs = qs.filter(name__icontains=search)
    return qs


def get_license_type(*, type_id: int) -> LicenseType:
    return LicenseType.objects.get(pk=type_id)


def list_license_type_options(*, actor: Any = None, q: str | None = None, include_ids: list[int] | None = None) -> QuerySet:
    cond = Q()
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        LicenseType.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


# Categories
def list_license_categories(*, search: str | None = None) -> QuerySet[LicenseCategory]:
    qs = LicenseCategory.objects.all().order_by("name", "pk")
    if search:
        qs = qs.filter(name__icontains=search)
    return qs


def get_license_category(*, category_id: int) -> LicenseCategory:
    return LicenseCategory.objects.get(pk=category_id)


def list_license_category_options(*, actor: Any = None, q: str | None = None, include_ids: list[int] | None = None) -> QuerySet:
    cond = Q()
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        LicenseCategory.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


# Restrictions
def list_license_restrictions(*, search: str | None = None) -> QuerySet[LicenseRestriction]:
    qs = LicenseRestriction.objects.all().order_by("name", "pk")
    if search:
        qs = qs.filter(name__icontains=search)
    return qs


def get_license_restriction(*, restriction_id: int) -> LicenseRestriction:
    return LicenseRestriction.objects.get(pk=restriction_id)


def list_license_restriction_options(*, actor: Any = None, q: str | None = None, include_ids: list[int] | None = None) -> QuerySet:
    cond = Q()
    if q:
        cond &= Q(name__icontains=q)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return (
        LicenseRestriction.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )
