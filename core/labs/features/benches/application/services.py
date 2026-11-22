"""Writes lock stations in PK order, then the bench, then its slots.

Station capacity edits follow the same parent-first protocol. Preliminary
placement is rechecked after locks rather than silently using a stale parent.
Equipment remains owned by the equipment assignment feature.
"""

from functools import wraps

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from rest_framework.exceptions import ErrorDetail
from rest_framework.exceptions import ValidationError as DRFValidationError

from core.labs.features.base.immutable import drop_unchanged_immutable_fields
from core.labs.features.benches.exceptions import BenchConflict
from core.labs.features.equipment.public import close_placements_for_location
from core.labs.models import (
    Bench,
    BenchBooking,
    BenchFavorite,
    BenchGroup,
    BenchType,
    Booking,
    Group,
    ResourceChangeLog,
    ResourceDowntime,
    ResourceLifecycleStatus,
    Station,
    StationSlot,
)
from core.labs.models.booking.base import BookingStatus, ensure_booking_status_transition
from core.labs.models.resource.base.availability import (
    bench_bookings_blocked_by_parents,
    booking_conflict_details,
)
from core.labs.models.resource.base.status import ensure_lifecycle_transition
from core.labs.models.resource.equipment.assignment import EquipmentAssignment
from core.users.public import LabsPermission, users_with_permission

from .policies import validate_capacity, validate_slot

FORCE_DELETE_REASON_MIN_LENGTH = 3
FORCE_DELETE_REASON_MAX_LENGTH = 500

WRITE_FIELDS = (
    "sku",
    "name",
    "group_id",
    "owner_id",
    "remark",
    "bench_group_id",
    "type_id",
    "description",
    "documentation_url",
    "setup_location_id",
    "station_slot_id",
    "lifecycle_status",
    "criticality",
    "requested_power_w",
    "requested_load_kg",
    "requested_cooling_w",
    "required_utilities",
    "commissioning_date",
    "last_inspected_at",
    "next_inspection_due_at",
)
PLACEMENT_FIELDS = ("setup_location_id", "station_slot_id")


def _command(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            with transaction.atomic():
                return function(*args, **kwargs)
        except (IntegrityError, ProtectedError) as exc:
            raise BenchConflict("The write conflicts with an existing resource or reference.") from exc

    return wrapped


def _apply(instance, data, allowed):
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValidationError({field: "This field is not writable." for field in unknown})
    for field, value in data.items():
        setattr(instance, field, value)


def _lock_stations(ids):
    ids = sorted({pk for pk in ids if pk is not None})
    stations = {item.pk: item for item in Station.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    if set(ids) != stations.keys():
        raise DRFValidationError(
            {"setup_location_id": [ErrorDetail("Select an existing setup location.", code="does_not_exist")]}
        )
    return stations


def _lock_bench(bench_id, data):
    old_station_id = Bench.objects.values_list("setup_location_id", flat=True).get(pk=bench_id)
    stations = _lock_stations((old_station_id, data.get("setup_location_id", old_station_id)))
    bench = Bench.objects.select_for_update().get(pk=bench_id)
    if bench.setup_location_id != old_station_id:
        raise BenchConflict("The bench moved concurrently; reload it and retry.")
    return bench, stations


def _validate_references(bench, data):
    if "group_id" in data and data["group_id"] is not None:
        try:
            Group.objects.get(pk=data["group_id"])
        except Group.DoesNotExist as error:
            raise DRFValidationError(
                {"group_id": [ErrorDetail("Select an existing reference.", code="does_not_exist")]}
            ) from error

    for field, model in (("type_id", BenchType), ("bench_group_id", BenchGroup)):
        # Inactive references remain readable and do not block unrelated edits.
        if field in data and data[field] is not None:
            try:
                reference = model.objects.get(pk=data[field])
            except model.DoesNotExist as error:
                raise DRFValidationError(
                    {field: [ErrorDetail("Select an existing reference.", code="does_not_exist")]}
                ) from error
            if not reference.active:
                raise ValidationError({field.removesuffix("_id"): "Select an active reference."})
    if not isinstance(bench.required_utilities, dict):
        raise ValidationError({"required_utilities": "Utilities must be an object."})


def _save(bench, stations, *, old_slot_id, data, actor):
    _validate_references(bench, data)
    if Bench.objects.filter(sku=bench.sku.strip()).exclude(pk=bench.pk).exists():
        raise BenchConflict("An active bench already uses this SKU.")
    ids = sorted({pk for pk in (old_slot_id, bench.station_slot_id) if pk is not None})
    slots = {item.pk: item for item in StationSlot.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    if set(ids) != slots.keys():
        raise DRFValidationError(
            {"station_slot_id": [ErrorDetail("Select an existing station slot.", code="does_not_exist")]}
        )
    if bench.setup_location_id is not None:
        bench.setup_location = stations[bench.setup_location_id]
        if bench.setup_location.lifecycle_status == ResourceLifecycleStatus.RETIRED:
            raise BenchConflict("The setup station is retired.")
        validate_capacity(
            bench,
            bench.setup_location,
            list(Bench.objects.filter(setup_location_id=bench.setup_location_id).exclude(pk=bench.pk)),
        )
    if bench.station_slot_id is not None:
        bench.station_slot = slots[bench.station_slot_id]
        if bench.setup_location_id is None:
            raise ValidationError({"station_slot": "A station slot requires a setup location."})
        validate_slot(bench, bench.station_slot, staying=old_slot_id == bench.station_slot_id)
        compatible_ids = set(bench.station_slot.compatible_bench_types.values_list("pk", flat=True))
        if compatible_ids and bench.type_id not in compatible_ids:
            raise ValidationError({"type": "Select a bench type compatible with the station slot."})
        if Bench.all_objects.filter(station_slot_id=bench.station_slot_id).exclude(pk=bench.pk).exists():
            raise BenchConflict("The station slot is already assigned.")
    # Slot occupancy is Bench.station_slot (one-to-one), never stored on the slot.
    bench.save(actor=actor)
    return bench


def _take_lifecycle(bench, data) -> None:
    """Apply the lifecycle transition rule to a ``lifecycle_status`` passed to create or update."""
    if "lifecycle_status" not in data:
        return
    target = data.pop("lifecycle_status")
    if bench.pk is not None:
        ensure_lifecycle_transition(current=bench.lifecycle_status, target=target)
    elif target not in ResourceLifecycleStatus.values:
        ensure_lifecycle_transition(current=ResourceLifecycleStatus.PLANNED, target=target)
    bench.lifecycle_status = target


def _ensure_bookings_fit_new_station(bench, station) -> None:
    """A move must not put future bookings inside the new station's or room's downtime (design rule 3).

    Race guard: the station and bench locks of ``_lock_bench``; downtime writers lock the same rows.
    """
    blocked = bench_bookings_blocked_by_parents(
        bench_ids=(bench.pk,),
        station=station,
        room=station.room,
        lab_operator_users=users_with_permission(LabsPermission.BENCH_BOOKING_BOOK_DURING_DOWNTIME),
    )
    if blocked:
        raise BenchConflict(
            "Bookings of this bench fall in downtime of the new station or room. Move or cancel them first.",
            details=booking_conflict_details(bench_booking_ids=blocked),
        )


def _after_lifecycle(bench, *, previous, actor) -> None:
    """Retiring ends the current downtime window and cancels windows planned for later."""
    if bench.lifecycle_status == ResourceLifecycleStatus.RETIRED and previous != ResourceLifecycleStatus.RETIRED:
        ResourceDowntime.objects.close_all(bench, actor=actor)


@_command
def create_bench(*, actor, **data):
    bench = Bench()
    data = dict(data)
    _take_lifecycle(bench, data)
    _apply(bench, data, WRITE_FIELDS)
    stations = _lock_stations((bench.setup_location_id,))
    return _save(bench, stations, old_slot_id=None, data=data, actor=actor)


@_command
def update_bench(*, bench_id, actor, **data):
    bench, stations = _lock_bench(bench_id, data)
    old_slot_id = bench.station_slot_id
    previous = bench.lifecycle_status
    old_station_id = bench.setup_location_id
    data = drop_unchanged_immutable_fields(bench, data)
    _take_lifecycle(bench, data)
    _apply(bench, data, WRITE_FIELDS)
    if bench.setup_location_id is not None and bench.setup_location_id != old_station_id:
        _ensure_bookings_fit_new_station(bench, stations[bench.setup_location_id])
    bench = _save(bench, stations, old_slot_id=old_slot_id, data=data, actor=actor)
    _after_lifecycle(bench, previous=previous, actor=actor)
    return bench


@_command
def change_bench_lifecycle(*, bench_id, actor, lifecycle_status):
    """Set ``lifecycle_status`` (planned, in_service, retired). Race guard: the bench lock protocol.

    Idempotent: the current value returns the bench unchanged. Out of service is a downtime window.
    """
    bench, _ = _lock_bench(bench_id, {})
    previous = bench.lifecycle_status
    ensure_lifecycle_transition(current=previous, target=lifecycle_status)
    if lifecycle_status == previous:
        return bench
    bench.lifecycle_status = lifecycle_status
    bench.save(actor=actor, update_fields=("lifecycle_status", "modified"))
    _after_lifecycle(bench, previous=previous, actor=actor)
    return bench


def place_bench(*, bench_id, actor, **data):
    if not data or set(data) - set(PLACEMENT_FIELDS):
        raise ValidationError("Provide setup_location and/or station_slot only.")
    return update_bench(bench_id=bench_id, actor=actor, **data)


def _resource_label(sku: str | None, name: str | None, pk: int) -> str:
    sku_text = (sku or "").strip()
    name_text = (name or "").strip()
    if sku_text and name_text:
        return f"{sku_text} — {name_text}"
    return sku_text or name_text or f"#{pk}"


@_command
def delete_bench(*, bench_id, actor):
    bench, _ = _lock_bench(bench_id, {})
    # Assign commands lock the bench before creating a live assignment.
    equipment_qs = EquipmentAssignment.objects.filter(
        bench_id=bench.pk,
        unassigned_at__isnull=True,
        equipment__deleted_at__isnull=True,
    )
    equipment_total = equipment_qs.count()
    equipment_rows = (
        list(
            equipment_qs.order_by("equipment_id").values_list(
                "equipment__sku", "equipment__name", "equipment_id", "equipment__kind__category__key"
            )[:5]
        )
        if equipment_total
        else []
    )
    equipment_labels = [_resource_label(sku, name, eq_id) for sku, name, eq_id, _ in equipment_rows]
    equipment_categories = [(category_key or "").strip() for _, _, _, category_key in equipment_rows]

    bookings_qs = BenchBooking.objects.filter(bench_id=bench.pk, status__in=Booking.ACTIVE_STATUSES)
    bookings_total = bookings_qs.count()
    booking_labels = (
        list(bookings_qs.order_by("starts_at", "pk").values_list("booking_code", flat=True)[:5])
        if bookings_total
        else []
    )
    if equipment_total or bookings_total:
        details: dict[str, object] = {}
        if equipment_total:
            details["equipment_total"] = equipment_total
            details["equipment"] = equipment_labels
            details["equipment_categories"] = equipment_categories
        if bookings_total:
            details["bookings_total"] = bookings_total
            details["bookings"] = booking_labels
        if equipment_total and bookings_total:
            message = "Unassign equipment and cancel active bookings before deleting this bench."
        elif equipment_total:
            message = "Unassign equipment before deleting this bench."
        else:
            message = "Cancel active bookings before deleting this bench."
        raise BenchConflict(message, details=details)
    if bench.station_slot_id is not None:
        StationSlot.objects.select_for_update().get(pk=bench.station_slot_id)
    bench.station_slot = None
    bench.setup_location = None
    bench.save(actor=actor)
    bench.soft_delete(actor=actor)


def force_delete_bench(*, bench_id, reason, confirm=True, actor):
    """Unassign equipment (returning units to Available), cancel active bench bookings, and soft-delete the bench.

    Race guard: validates input before opening a transaction, then locks the station and bench
    via ``_lock_bench``, closes active equipment assignments (PK order), cancels active bench
    bookings (PK order), closes open downtime windows, releases the station slot, writes a
    ``ResourceChangeLog`` entry, and soft-deletes the bench.
    Idempotency: calling again on a soft-deleted bench raises ``Bench.DoesNotExist`` (404).
    """
    if confirm is not True:
        raise ValidationError({"confirm": "Explicit confirmation is required to force-delete a bench."})
    cleaned_reason = (reason or "").strip()
    if len(cleaned_reason) < FORCE_DELETE_REASON_MIN_LENGTH:
        raise ValidationError(
            {"reason": f"Provide a reason of at least {FORCE_DELETE_REASON_MIN_LENGTH} characters."}
        )
    if len(cleaned_reason) > FORCE_DELETE_REASON_MAX_LENGTH:
        raise ValidationError({"reason": f"Use at most {FORCE_DELETE_REASON_MAX_LENGTH} characters."})
    return _force_delete_bench_tx(bench_id=bench_id, reason=cleaned_reason, actor=actor)


@_command
def _force_delete_bench_tx(*, bench_id, reason: str, actor):
    bench, _ = _lock_bench(bench_id, {})
    released_equipment = close_placements_for_location(bench_id=bench.pk, actor=actor)
    active_bookings = list(
        BenchBooking.objects.select_for_update()
        .filter(bench_id=bench.pk, status__in=Booking.ACTIVE_STATUSES)
        .order_by("pk")
    )
    cancellation_reason = f"Bench force-deleted: {reason}"
    for booking in active_bookings:
        ensure_booking_status_transition(current_status=booking.status, target_status=BookingStatus.CANCELLED)
        booking.status = BookingStatus.CANCELLED
        booking.cancellation_reason = cancellation_reason
        booking.save(update_fields=("status", "cancellation_reason", "modified"))
    ResourceDowntime.objects.close_all(bench, actor=actor)
    if bench.station_slot_id is not None:
        StationSlot.objects.select_for_update().get(pk=bench.station_slot_id)
    released = {"equipment": released_equipment, "bookings": len(active_bookings)}
    acting_user = actor if getattr(actor, "is_authenticated", False) else None
    if acting_user is not None:
        content_type = ContentType.objects.get_for_model(bench, for_concrete_model=False)
        ResourceChangeLog(
            resource_content_type=content_type,
            resource_object_id=str(bench.pk),
            action=ResourceChangeLog.Action.DELETE,
            field_name="force_delete",
            old_value=None,
            new_value={"reason": reason, "released": released},
        ).save(actor=acting_user)
    bench.station_slot = None
    bench.setup_location = None
    bench.save(actor=actor)
    bench.soft_delete(actor=actor)
    return {"id": bench.pk, "released": released}


@_command
def add_favorite(*, bench_id, actor):
    bench = Bench.objects.select_for_update().get(pk=bench_id)
    favorite, _ = BenchFavorite.objects.get_or_create(bench=bench, user=actor)
    return favorite


@_command
def remove_favorite(*, bench_id, actor):
    # Allow a user to remove a retained membership after its bench was deleted.
    Bench.all_objects.select_for_update().get(pk=bench_id)
    BenchFavorite.objects.filter(bench_id=bench_id, user=actor).delete()


@_command
def save_reference(*, model, actor, reference_id=None, **data):
    model = _reference_model(model)
    if model is None:
        raise ValueError("Unsupported bench reference model.")
    instance = model() if reference_id is None else model.objects.select_for_update().get(pk=reference_id)
    _apply(instance, data, ("name", "description", "active"))
    instance.name = instance.name.strip()
    if model.objects.filter(name=instance.name).exclude(pk=instance.pk).exists():
        raise BenchConflict("The reference name already exists.")
    instance.full_clean()
    instance.save(actor=actor)
    return instance


@_command
def retire_reference(*, model, reference_id, actor):
    # Retire rather than delete protected references, preserving historical links.
    return save_reference(model=model, reference_id=reference_id, actor=actor, active=False)


def _reference_model(model):
    if model in ("group", BenchGroup):
        return BenchGroup
    if model in ("type", BenchType):
        return BenchType
    return None


__all__ = [
    "add_favorite",
    "change_bench_lifecycle",
    "create_bench",
    "delete_bench",
    "force_delete_bench",
    "place_bench",
    "remove_favorite",
    "retire_reference",
    "save_reference",
    "update_bench",
]
