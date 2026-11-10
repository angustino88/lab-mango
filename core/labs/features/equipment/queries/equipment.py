"""Read-only selectors for equipment resources."""

from typing import Any

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Case, CharField, Exists, OuterRef, Prefetch, Q, QuerySet, Subquery, Value, When
from django.db.models.functions import Cast, Now

from core.labs.features.equipment.contracts import ActiveEquipmentBenchAssignment
from core.labs.models import (
    Equipment,
    EquipmentCategory,
    EquipmentCondition,
    EquipmentDisplayStatus,
    EquipmentKind,
    EquipmentLifecycleState,
    EquipmentLoan,
    EquipmentManufacturer,
    EquipmentProductModel,
    EquipmentType,
    PurchaseItemResource,
    ResourceServiceRecord,
)
from core.labs.models.resource.base.generic_links import resource_root_model
from core.labs.models.resource.base.resource import ResourceGroup
from core.labs.models.resource.equipment.assignment import EquipmentAssignment


def display_status_expression() -> Case:
    """``display_status`` from the stored facts; first matching row wins (redesign, display status).

    Needs ``latest_calibration_due_at`` on the queryset.
    """
    on_loan = Exists(EquipmentLoan.objects.filter(equipment_id=OuterRef("pk"), returned_at__isnull=True))
    on_bench = Exists(EquipmentAssignment.objects.filter(equipment_id=OuterRef("pk"), unassigned_at__isnull=True))
    calibration_overdue = Q(calibration_required=True) & (
        Q(latest_calibration_due_at__isnull=True) | Q(latest_calibration_due_at__lt=Now())
    )
    status = EquipmentDisplayStatus
    # Q() wraps `condition` lookups: When() has its own `condition` parameter.
    return Case(
        When(lifecycle_state=EquipmentLifecycleState.PLANNED, then=Value(status.ON_ORDER)),
        When(lifecycle_state=EquipmentLifecycleState.TRANSFERRED_OUT, then=Value(status.TRANSFERRED)),
        When(lifecycle_state=EquipmentLifecycleState.RETIRED, then=Value(status.RETIRED)),
        When(lifecycle_state=EquipmentLifecycleState.LOST, then=Value(status.LOST)),
        When(Q(condition=EquipmentCondition.OUT_OF_SERVICE), then=Value(status.BROKEN)),
        When(Q(condition=EquipmentCondition.IN_MAINTENANCE), then=Value(status.MAINTENANCE)),
        When(on_loan, then=Value(status.BORROWED)),
        When(on_bench, then=Value(status.IN_USE)),
        When(calibration_overdue, then=Value(status.CALIBRATION_OVERDUE)),
        default=Value(status.AVAILABLE),
        output_field=CharField(),
    )


def _latest_calibration(queryset) -> QuerySet:
    # Latest calibration, matched exactly like ResourceModel.service_records (root and own
    # content types). Filter by app_label/model (joined in SQL) so building it needs no DB access.
    linked_models = {resource_root_model(queryset.model), queryset.model._meta.concrete_model}
    return ResourceServiceRecord.objects.filter(
        resource_content_type__app_label=Equipment._meta.app_label,
        resource_content_type__model__in=sorted(model._meta.model_name for model in linked_models),
        resource_object_id=Cast(OuterRef("pk"), CharField()),
        kind=ResourceServiceRecord.Kind.CALIBRATION,
    ).order_by("-performed_at", "-id")


def with_display_status(queryset):
    """Annotate ``display_status`` (and the calibration due date it needs) for filters and counts."""
    if "latest_calibration_due_at" not in queryset.query.annotations:
        queryset = queryset.annotate(
            latest_calibration_due_at=Subquery(_latest_calibration(queryset).values("next_due_at")[:1])
        )
    return queryset.annotate(display_status=display_status_expression())


def with_equipment_info(queryset):
    """Project canonical equipment acquisition data onto base or category queries."""
    acquisition = PurchaseItemResource.objects.filter(
        resource_type__app_label=Equipment._meta.app_label,
        resource_type__model=Equipment._meta.model_name,
        resource_id=OuterRef("pk"),
    )
    # Read by Equipment.last_calibrated_at / next_calibration_due_at / calibration_overdue,
    # which otherwise run a query each per serialized row.
    calibration = _latest_calibration(queryset)
    queryset = queryset.annotate(
        latest_calibration_at=Subquery(calibration.values("performed_at")[:1]),
        latest_calibration_due_at=Subquery(calibration.values("next_due_at")[:1]),
        acquisition_price=Subquery(acquisition.values("acquisition_price")[:1]),
        acquisition_currency=Subquery(acquisition.values("purchase_item__purchase__currency")[:1]),
        has_active_assignment=Exists(
            EquipmentAssignment.objects.filter(
                equipment_id=OuterRef("pk"),
                unassigned_at__isnull=True,
            )
        ),
        on_loan=Exists(EquipmentLoan.objects.filter(equipment_id=OuterRef("pk"), returned_at__isnull=True)),
        loan_overdue=Exists(
            EquipmentLoan.objects.filter(equipment_id=OuterRef("pk"), returned_at__isnull=True, due_at__lt=Now())
        ),
    )
    return with_display_status(queryset)


ACTIVE_PLACEMENT_ATTR = "active_placements"
ACTIVE_LOAN_ATTR = "active_loans"


def with_active_placement(queryset: QuerySet) -> QuerySet:
    """Prefetch each unit's active placement (bench, station, room, or note) in one query per page."""
    return queryset.prefetch_related(
        Prefetch(
            "bench_assignments",
            queryset=EquipmentAssignment.all_placements.filter(unassigned_at__isnull=True).select_related(
                "bench", "station", "room"
            ),
            to_attr=ACTIVE_PLACEMENT_ATTR,
        )
    )


def with_active_loan(queryset: QuerySet) -> QuerySet:
    """Prefetch each unit's open loan with its borrower in one query per page."""
    return queryset.prefetch_related(
        Prefetch(
            "loans",
            queryset=EquipmentLoan.objects.filter(returned_at__isnull=True).select_related("borrower"),
            to_attr=ACTIVE_LOAN_ATTR,
        )
    )


def list_equipment(
    *,
    category: str | None = None,
    kind: str | int | None = None,
    equipment_type: int | None = None,
    manufacturer: int | None = None,
    status: str | None = None,
    assigned: bool | None = None,
    search: str | None = None,
) -> QuerySet[Equipment]:
    queryset = (
        Equipment.objects.filter(deleted_at__isnull=True)
        .select_related(
            "kind",
            "kind__category",
            "type",
            "manufacturer",
            "product_model",
            "owner",
            "department",
            "group",
        )
        .order_by("kind__category__name", "kind__name", "name", "id")
    )
    queryset = with_active_loan(with_active_placement(with_equipment_info(queryset)))

    if category:
        queryset = queryset.filter(kind__category_id=category)
    if kind:
        kind_filter = Q(kind_id=kind) if isinstance(kind, int) or str(kind).isdigit() else Q(kind__key=kind)
        queryset = queryset.filter(kind_filter)
    if equipment_type:
        queryset = queryset.filter(type_id=equipment_type)
    if manufacturer:
        queryset = queryset.filter(manufacturer_id=manufacturer)
    if status:
        queryset = queryset.filter(display_status=status)
    if assigned is not None:
        active_assignment = EquipmentAssignment.objects.filter(
            equipment_id=OuterRef("pk"),
            unassigned_at__isnull=True,
        )
        queryset = queryset.annotate(has_active_assignment=Exists(active_assignment))
        queryset = queryset.filter(has_active_assignment=assigned)
    if search:
        queryset = queryset.filter(
            Q(sku__icontains=search)
            | Q(name__icontains=search)
            | Q(serial_number__icontains=search)
            | Q(log_label__icontains=search)
            | Q(kind__name__icontains=search)
            | Q(manufacturer__name__icontains=search)
            | Q(product_model__name__icontains=search)
        )

    # Forward FK joins and scalar Subquery/Exists projections preserve one row per equipment.
    return queryset


def get_equipment(equipment_id: int) -> Equipment:
    """Return one visible equipment record with the list projection applied."""
    return list_equipment().get(id=equipment_id)


def get_equipment_for_mapping(*, equipment_id: int) -> Equipment | None:
    """Return only an active equipment row for the cross-resource mapping read boundary."""
    return (
        Equipment.objects.filter(pk=equipment_id, deleted_at__isnull=True)
        .values("id", "uid", "sku", "name", "kind__category_id", "kind__category__name")
        .first()
    )


def equipment_mapping_rows(*, equipment_ids=(), bench_ids=(), station_ids=(), room_ids=()):
    active_assignments = EquipmentAssignment.objects.filter(
        equipment_id=OuterRef("pk"),
        unassigned_at__isnull=True,
        bench__deleted_at__isnull=True,
        equipment__deleted_at__isnull=True,
    ).order_by("pk")
    queryset = (
        Equipment.objects.filter(deleted_at__isnull=True)
        .select_related("kind__category")
        .annotate(
            mapping_bench_id=Subquery(active_assignments.values("bench_id")[:1]),
            mapping_assignment_id=Subquery(active_assignments.values("id")[:1]),
            mapping_role=Subquery(active_assignments.values("role")[:1]),
            mapping_position=Subquery(active_assignments.values("position")[:1]),
            mapping_monitor=Subquery(active_assignments.values("monitor")[:1]),
            mapping_assigned_at=Subquery(active_assignments.values("assigned_at")[:1]),
        )
    )
    if equipment_ids:
        queryset = queryset.filter(pk__in=equipment_ids)
    elif bench_ids:
        queryset = queryset.filter(
            bench_assignments__bench_id__in=bench_ids,
            bench_assignments__unassigned_at__isnull=True,
            bench_assignments__bench__deleted_at__isnull=True,
        )
    elif station_ids:
        queryset = queryset.filter(
            bench_assignments__bench__setup_location_id__in=station_ids,
            bench_assignments__unassigned_at__isnull=True,
            bench_assignments__bench__deleted_at__isnull=True,
        )
    elif room_ids:
        queryset = queryset.filter(
            bench_assignments__bench__setup_location__room_id__in=room_ids,
            bench_assignments__unassigned_at__isnull=True,
            bench_assignments__bench__deleted_at__isnull=True,
            bench_assignments__bench__setup_location__deleted_at__isnull=True,
        )
    else:
        return queryset.none().values("id", "uid", "sku", "name", "kind__category_id", "kind__category__name")
    return (
        queryset.order_by("pk")
        .distinct()
        .values(
            "id",
            "uid",
            "sku",
            "name",
            "kind__category_id",
            "kind__category__name",
            "mapping_bench_id",
            "mapping_assignment_id",
            "mapping_role",
            "mapping_position",
            "mapping_monitor",
            "mapping_assigned_at",
        )
    )


def active_bench_assignment_mapping_rows(*, bench_ids=(), equipment_ids=(), station_ids=(), room_ids=()):
    queryset = EquipmentAssignment.objects.filter(
        unassigned_at__isnull=True,
        bench__deleted_at__isnull=True,
        equipment__deleted_at__isnull=True,
    )
    if bench_ids:
        queryset = queryset.filter(bench_id__in=bench_ids)
    elif equipment_ids:
        queryset = queryset.filter(equipment_id__in=equipment_ids)
    elif station_ids:
        queryset = queryset.filter(
            bench__setup_location_id__in=station_ids,
            bench__setup_location__deleted_at__isnull=True,
        )
    elif room_ids:
        queryset = queryset.filter(
            bench__setup_location__room_id__in=room_ids,
            bench__setup_location__deleted_at__isnull=True,
        )
    else:
        return queryset.none().values("id", "bench_id", "equipment_id", "role", "position", "monitor", "assigned_at")
    return queryset.order_by("pk").values(
        "id", "bench_id", "equipment_id", "role", "position", "monitor", "assigned_at"
    )


def equipment_reference_data() -> dict[str, QuerySet]:
    """Return active reference rows used by the generic equipment form."""
    return {
        "categories": EquipmentCategory.objects.filter(active=True),
        "kinds": EquipmentKind.objects.filter(active=True, category__active=True),
        "types": EquipmentType.objects.filter(active=True, kind__active=True),
        "manufacturers": EquipmentManufacturer.objects.filter(active=True),
        "product_models": EquipmentProductModel.objects.filter(active=True, manufacturer__active=True),
    }


def category_queryset(model: type[models.Model], fields: tuple[str, ...], *, related: tuple[str, ...] = ()):
    """Build a category list projection using its declared relation fields.

    ``related`` names extra reverse one-to-one relations to join for detail projections.
    """
    joins = [
        "kind",
        "kind__category",
        "type",
        "manufacturer",
        "product_model",
        "owner",
        "department",
        "group",
        *related,
    ]
    prefetches = []
    for name in fields:
        field = model._meta.get_field(name)
        if field.many_to_many:
            prefetches.append(name)
        elif field.many_to_one:
            joins.append(name)
    return with_active_loan(
        with_active_placement(
            with_equipment_info(
                model.objects.filter(deleted_at__isnull=True)
                .select_related(*joins)
                .prefetch_related(*prefetches)
                .order_by("name", "sku", "pk")
            )
        )
    )


def category_reference_data(
    category_key: str,
    lookups: tuple[tuple[str, type[models.Model], str], ...],
) -> dict[str, QuerySet]:
    """Return reference rows needed to create or edit category equipment."""
    # Match the stable category key; rows not migrated to a key fall back to the name,
    # mirroring EquipmentCategory.effective_key. Renaming a category must not hide its kinds.
    by_key = Q(key=category_key) | Q(key__isnull=True, name__iexact=category_key)
    kinds = EquipmentKind.objects.filter(
        Q(category__key=category_key) | Q(category__key__isnull=True, category__name__iexact=category_key),
        active=True,
        category__active=True,
    ).select_related("category")
    active_category = EquipmentCategory.objects.filter(by_key, active=True)
    types = EquipmentType.objects.filter(
        active=True,
        kind__active=True,
        kind__in=kinds,
    )
    manufacturers = EquipmentManufacturer.objects.filter(
        active=True,
        categories__in=active_category,
    ).distinct()
    payload = {
        "kinds": kinds,
        "types": types,
        "manufacturers": manufacturers,
        "product_models": EquipmentProductModel.objects.filter(
            active=True,
            manufacturer__active=True,
            manufacturer__categories__in=active_category,
            equipment_type__active=True,
            equipment_type__kind__active=True,
            equipment_type__kind__in=kinds,
            equipment_type__kind__category__in=active_category,
        ).distinct(),
        "groups": ResourceGroup.objects.filter(active=True),
        "owners": get_user_model().objects.filter(is_active=True).order_by("username", "pk"),
    }
    payload.update({key: model.objects.all() for key, model, _ in lookups})
    return payload


def list_equipment_options(
    *,
    assignable: bool | None = None,
    category_id: int | None = None,
    category: str | int | None = None,
    kind_id: int | None = None,
    kind: str | int | None = None,
    type_id: int | None = None,
    equipment_type: int | None = None,
    manufacturer_id: int | None = None,
    manufacturer: int | None = None,
    lifecycle_state: str | None = None,
    status: str | None = None,
    assigned: bool | None = None,
    q: str | None = None,
    search: str | None = None,
    include_ids: Any = None,
    actor: Any = None,
) -> QuerySet[Equipment]:
    """Return equipment options for selectors, projecting only id, sku, and name.

    Reserved for selector data: GET /api/<resource>/options/.
    Ordered stably by name. Uses Exists(...) for has/has-not filters.
    """
    queryset = Equipment.objects.filter(deleted_at__isnull=True)

    active_assignment = EquipmentAssignment.objects.filter(
        equipment_id=OuterRef("pk"),
        unassigned_at__isnull=True,
    )

    cat_val = category_id if category_id is not None else category
    kind_val = kind_id if kind_id is not None else kind
    type_val = type_id if type_id is not None else equipment_type
    mfr_val = manufacturer_id if manufacturer_id is not None else manufacturer
    search_val = q or search

    cond = Q(deleted_at__isnull=True)

    if cat_val:
        category_filter = (
            Q(kind__category_id=cat_val)
            if isinstance(cat_val, int) or str(cat_val).isdigit()
            else Q(kind__category__name__iexact=cat_val)
        )
        cond &= category_filter

    if kind_val:
        kind_filter = (
            Q(kind_id=kind_val) if isinstance(kind_val, int) or str(kind_val).isdigit() else Q(kind__key=kind_val)
        )
        cond &= kind_filter

    if type_val:
        cond &= Q(type_id=type_val)

    if mfr_val:
        cond &= Q(manufacturer_id=mfr_val)

    # Has / has-not filter using Exists(...)
    if assigned is not None:
        if assigned:
            cond &= Exists(active_assignment)
        else:
            cond &= ~Exists(active_assignment)

    # Assignable: available right now (in service, operational, not on a bench, calibrated).
    if assignable is not None or status:
        queryset = with_display_status(queryset)
    if assignable is not None:
        available = Q(display_status=EquipmentDisplayStatus.AVAILABLE)
        cond &= available if assignable else ~available

    if status:
        cond &= Q(display_status=status)

    if lifecycle_state:
        cond &= Q(lifecycle_state=lifecycle_state)

    if search_val:
        cond &= (
            Q(sku__icontains=search_val)
            | Q(name__icontains=search_val)
            | Q(serial_number__icontains=search_val)
            | Q(log_label__icontains=search_val)
            | Q(kind__name__icontains=search_val)
            | Q(manufacturer__name__icontains=search_val)
            | Q(product_model__name__icontains=search_val)
        )

    query_filter = cond
    if include_ids:
        query_filter |= Q(pk__in=include_ids, deleted_at__isnull=True)

    return queryset.filter(query_filter).only("id", "sku", "name").order_by("name", "id")


def category_options_queryset(
    model: type[models.Model],
    fields: tuple[str, ...] = (),
    *,
    assignable: bool | None = None,
    kind_id: int | None = None,
    kind: str | int | None = None,
    type_id: int | None = None,
    equipment_type: int | None = None,
    manufacturer_id: int | None = None,
    manufacturer: int | None = None,
    lifecycle_state: str | None = None,
    status: str | None = None,
    assigned: bool | None = None,
    q: str | None = None,
    search: str | None = None,
    include_ids: Any = None,
    actor: Any = None,
) -> QuerySet:
    """Return category equipment options for selectors, projecting only id, sku, and name.

    Reserved for selector data: GET /api/<resource>/options/.
    Ordered stably by name. Uses Exists(...) for has/has-not filters.
    """
    queryset = model.objects.filter(deleted_at__isnull=True)

    active_assignment = EquipmentAssignment.objects.filter(
        equipment_id=OuterRef("pk"),
        unassigned_at__isnull=True,
    )

    kind_val = kind_id if kind_id is not None else kind
    type_val = type_id if type_id is not None else equipment_type
    mfr_val = manufacturer_id if manufacturer_id is not None else manufacturer
    search_val = q or search

    cond = Q(deleted_at__isnull=True)

    if kind_val:
        kind_filter = (
            Q(kind_id=kind_val) if isinstance(kind_val, int) or str(kind_val).isdigit() else Q(kind__key=kind_val)
        )
        cond &= kind_filter

    if type_val:
        cond &= Q(type_id=type_val)

    if mfr_val:
        cond &= Q(manufacturer_id=mfr_val)

    # Has / has-not filter using Exists(...)
    if assigned is not None:
        if assigned:
            cond &= Exists(active_assignment)
        else:
            cond &= ~Exists(active_assignment)

    # Assignable: available right now (in service, operational, not on a bench, calibrated).
    if assignable is not None or status:
        queryset = with_display_status(queryset)
    if assignable is not None:
        available = Q(display_status=EquipmentDisplayStatus.AVAILABLE)
        cond &= available if assignable else ~available

    if status:
        cond &= Q(display_status=status)

    if lifecycle_state:
        cond &= Q(lifecycle_state=lifecycle_state)

    if search_val:
        cond &= (
            Q(sku__icontains=search_val)
            | Q(name__icontains=search_val)
            | Q(serial_number__icontains=search_val)
            | Q(log_label__icontains=search_val)
            | Q(kind__name__icontains=search_val)
        )

    query_filter = cond
    if include_ids:
        query_filter |= Q(pk__in=include_ids, deleted_at__isnull=True)

    return queryset.filter(query_filter).only("id", "sku", "name").order_by("name", "id")


def get_active_equipment_assignment(*, equipment_id: int) -> EquipmentAssignment:
    """Return the active bench assignment for an equipment record."""
    return EquipmentAssignment.objects.select_related("equipment", "bench").get(
        equipment_id=equipment_id, unassigned_at__isnull=True
    )


def active_equipment_bench_assignment(*, equipment_id: int) -> ActiveEquipmentBenchAssignment | None:
    """Return the active equipment-to-live-bench binding as an immutable projection."""
    row = (
        EquipmentAssignment.objects.filter(
            equipment_id=equipment_id,
            unassigned_at__isnull=True,
            equipment__deleted_at__isnull=True,
            bench__deleted_at__isnull=True,
        )
        .values("equipment_id", "bench_id")
        .first()
    )
    if row is None:
        return None
    return ActiveEquipmentBenchAssignment(equipment_id=row["equipment_id"], bench_id=row["bench_id"])


def lock_active_equipment_bench_assignment(*, equipment_id: int) -> ActiveEquipmentBenchAssignment | None:
    """Lock the equipment row and project its current active bench assignment.

    All equipment assignment writers lock Equipment before changing EquipmentAssignment. Holding
    this owner-row lock through the caller's transaction therefore prevents the binding changing
    between authorization and the caller's write.

    Must run inside the caller's transaction: opening one here would commit and release the
    lock on return. ``select_for_update`` raises TransactionManagementError in autocommit mode.
    """
    equipment = Equipment.objects.select_for_update().filter(pk=equipment_id, deleted_at__isnull=True).first()
    if equipment is None:
        return None
    assignment = (
        EquipmentAssignment.objects.filter(
            equipment_id=equipment.pk,
            unassigned_at__isnull=True,
            bench__deleted_at__isnull=True,
        )
        .values("equipment_id", "bench_id")
        .first()
    )
    if assignment is None:
        return None
    return ActiveEquipmentBenchAssignment(
        equipment_id=assignment["equipment_id"],
        bench_id=assignment["bench_id"],
    )
