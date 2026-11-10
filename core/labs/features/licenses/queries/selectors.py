"""Read queries for license inventory and acquisition information."""

from django.db.models import Count, IntegerField, OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce

from core.labs.models import License, LicenseAgreement, LicenseStatusRecord, PurchaseItemResource
from core.labs.models.resource.license.assignment import LicenseAssignment


def get_license(*, license_id: int) -> License | None:
    """Return a license through the same projection used by inventory lists."""
    return list_licenses().filter(pk=license_id).first()


def get_active_license(*, license_id: int) -> License | None:
    """Return one active license without acquisition projection for existence checks."""
    return License.objects.filter(pk=license_id, deleted_at__isnull=True).first()


def get_license_for_mapping(*, license_id: int) -> License | None:
    """Return a minimal active license projection for resource mappings; excludes commercial data."""
    return (
        License.objects.filter(pk=license_id, deleted_at__isnull=True)
        .select_related("category")
        .only("id", "uid", "sku", "name", "category__id", "category__name")
        .first()
    )


def license_mapping_rows(*, license_ids=()):
    queryset = License.objects.filter(deleted_at__isnull=True).select_related("category")
    if license_ids is not None:
        queryset = queryset.filter(pk__in=license_ids)
    else:
        return queryset.none().values("id", "uid", "sku", "name", "category_id", "category__name")
    return queryset.order_by("pk").values("id", "uid", "sku", "name", "category_id", "category__name")


def active_license_assignment_mapping_rows(*, equipment_ids=(), bench_ids=(), station_ids=(), room_ids=()):
    queryset = LicenseAssignment.objects.filter(
        unassigned_at__isnull=True,
        equipment__deleted_at__isnull=True,
        license__deleted_at__isnull=True,
        equipment__bench_assignments__bench__deleted_at__isnull=True,
    )
    if equipment_ids:
        queryset = queryset.filter(equipment_id__in=equipment_ids)
    elif bench_ids:
        queryset = queryset.filter(
            equipment__bench_assignments__bench_id__in=bench_ids,
            equipment__bench_assignments__unassigned_at__isnull=True,
            equipment__bench_assignments__bench__deleted_at__isnull=True,
        )
    elif station_ids:
        queryset = queryset.filter(
            equipment__bench_assignments__bench__setup_location_id__in=station_ids,
            equipment__bench_assignments__unassigned_at__isnull=True,
            equipment__bench_assignments__bench__deleted_at__isnull=True,
        )
    elif room_ids:
        queryset = queryset.filter(
            equipment__bench_assignments__bench__setup_location__room_id__in=room_ids,
            equipment__bench_assignments__unassigned_at__isnull=True,
            equipment__bench_assignments__bench__deleted_at__isnull=True,
        )
    else:
        return queryset.none().values("id", "equipment_id", "license_id", "assigned_at")
    return queryset.order_by("pk").values("id", "equipment_id", "license_id", "assigned_at")


def list_licenses(*, search: str | None = None) -> QuerySet[License]:
    latest_status = LicenseStatusRecord.objects.filter(
        license_id=OuterRef("pk"),
    ).order_by("-created", "-id")
    acquisition = PurchaseItemResource.objects.filter(
        resource_type__app_label=License._meta.app_label,
        resource_type__model=License._meta.model_name,
        resource_id=OuterRef("pk"),
    )
    active_seats = (
        LicenseAssignment.objects.filter(license_id=OuterRef("pk"), unassigned_at__isnull=True)
        .order_by()
        .values("license_id")
        .annotate(total=Count("pk"))
        .values("total")
    )
    queryset = (
        License.objects.filter(deleted_at__isnull=True)
        .select_related("product", "vendor", "type", "category", "restriction", "owner")
        .annotate(
            # Read by License.seats_in_use; one correlated subquery instead of a COUNT per row.
            active_seat_count=Coalesce(Subquery(active_seats, output_field=IntegerField()), 0),
            current_status=Subquery(latest_status.values("status")[:1]),
            acquisition_price=Subquery(acquisition.values("acquisition_price")[:1]),
            acquisition_currency=Subquery(acquisition.values("purchase_item__purchase__currency")[:1]),
        )
        .order_by("name", "id")
    )
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(sku__icontains=search)
            | Q(product__name__icontains=search)
            | Q(vendor__name__icontains=search)
        )
    return queryset


def list_license_agreements(*, license_id: int) -> QuerySet[LicenseAgreement]:
    """Read agreements for an active license, or return no rows if it is absent."""
    return LicenseAgreement.objects.filter(license_id=license_id).order_by("-created", "-pk")


__all__ = [
    "active_license_assignment_mapping_rows",
    "get_active_license",
    "get_license",
    "get_license_for_mapping",
    "license_mapping_rows",
    "list_license_agreements",
    "list_licenses",
]
