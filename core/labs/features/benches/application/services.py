"""Writes lock stations in PK order, then the bench, then its slots.

Station capacity edits follow the same parent-first protocol. Preliminary
placement is rechecked after locks rather than silently using a stale parent.
Equipment remains owned by the equipment assignment feature.
"""

from functools import wraps

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from rest_framework.exceptions import ErrorDetail
from rest_framework.exceptions import ValidationError as DRFValidationError

from core.labs.features.benches.exceptions import BenchConflict
from core.labs.models import (
    Bench,
    BenchFavorite,
    BenchGroup,
    BenchType,
    Group,
    Station,
    StationSlot,
)
from core.labs.models.resource.equipment.assignment import EquipmentAssignment

from .policies import validate_capacity, validate_slot

WRITE_FIELDS = (
    "sku",
    "name",
    "group_id",
    "owner_id",
    "remark",
    "image",
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
    bench.save(actor=actor)
    if old_slot_id is not None and old_slot_id != bench.station_slot_id:
        old_slot = slots[old_slot_id]
        if old_slot.status == "occupied":
            old_slot.status = "available"
            old_slot.save(actor=actor)
    if bench.station_slot_id is not None:
        slot = slots[bench.station_slot_id]
        if slot.status != "occupied":
            slot.status = "occupied"
            slot.save(actor=actor)
    return bench


@_command
def create_bench(*, actor, **data):
    bench = Bench()
    _apply(bench, data, WRITE_FIELDS)
    stations = _lock_stations((bench.setup_location_id,))
    return _save(bench, stations, old_slot_id=None, data=data, actor=actor)


@_command
def update_bench(*, bench_id, actor, **data):
    bench, stations = _lock_bench(bench_id, data)
    old_slot_id = bench.station_slot_id
    _apply(bench, data, WRITE_FIELDS)
    return _save(bench, stations, old_slot_id=old_slot_id, data=data, actor=actor)


def place_bench(*, bench_id, actor, **data):
    if not data or set(data) - set(PLACEMENT_FIELDS):
        raise ValidationError("Provide setup_location and/or station_slot only.")
    return update_bench(bench_id=bench_id, actor=actor, **data)


@_command
def delete_bench(*, bench_id, actor):
    bench, _ = _lock_bench(bench_id, {})
    # Assign commands lock the bench before creating a live assignment.
    if EquipmentAssignment.objects.filter(bench_id=bench.pk, unassigned_at__isnull=True).exists():
        raise BenchConflict("Unassign equipment before deleting this bench.")
    from core.labs.models import BenchBooking, Booking

    if BenchBooking.objects.filter(bench_id=bench.pk, status__in=Booking.ACTIVE_STATUSES).exists():
        raise BenchConflict("Cancel active bookings before deleting this bench.")
    slot = None
    if bench.station_slot_id is not None:
        slot = StationSlot.objects.select_for_update().get(pk=bench.station_slot_id)
    bench.station_slot = None
    bench.setup_location = None
    bench.save(actor=actor)
    bench.soft_delete(actor=actor)
    if slot is not None and slot.status == "occupied":
        slot.status = "available"
        slot.save(actor=actor)


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
    "create_bench",
    "delete_bench",
    "place_bench",
    "remove_favorite",
    "retire_reference",
    "save_reference",
    "update_bench",
]
