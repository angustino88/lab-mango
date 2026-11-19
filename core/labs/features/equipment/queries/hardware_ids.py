"""Hardware-ID reads: a unit's registered IDs, and matching reported IDs to inventory."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from django.db.models import Q, QuerySet

from core.labs.features.equipment.contracts import DeviceEquipmentMatch
from core.labs.models import EquipmentInterface
from core.labs.models.resource.equipment.hardware_id import EquipmentHardwareId

HardwareIdPair = tuple[str, str]  # (kind, normalised value)
MAX_EVIDENCE = 200


def list_hardware_ids(*, equipment_id: int) -> QuerySet[EquipmentHardwareId]:
    return (
        EquipmentHardwareId.objects.filter(equipment_id=equipment_id)
        .select_related("computing")
        .order_by("kind", "value", "pk")
    )


def _valid_for(computing_id: int) -> Q:
    """Device-reported IDs are global; port-bound ones only count on the computer they were read on."""
    return Q(computing__isnull=True) | Q(computing_id=computing_id)


def match_hardware_ids(
    *, computing_id: int, evidence: Iterable[tuple[tuple[HardwareIdPair, ...], str]]
) -> dict[tuple[tuple[HardwareIdPair, ...], str], DeviceEquipmentMatch]:
    """Match each device's reported IDs (plus its interface name) to at most one active unit.

    ``matched``: all registered IDs among the reported ones belong to one unit; ``ambiguous``: they
    belong to different units; ``unmatched``: none is registered. The interface is the unit's
    interface with the reported name, when it has one. One query for the whole batch.
    """
    items = list(dict.fromkeys(evidence))
    if len(items) > MAX_EVIDENCE:
        raise ValueError(f"At most {MAX_EVIDENCE} device records are supported.")
    pairs = {pair for ids, _ in items for pair in ids}
    owners: dict[HardwareIdPair, set[int]] = defaultdict(set)
    if pairs:
        by_pair = Q()
        for kind, value in pairs:
            by_pair |= Q(kind=kind, value=value)
        rows = EquipmentHardwareId.objects.filter(
            by_pair, _valid_for(computing_id), equipment__deleted_at__isnull=True
        ).values_list("kind", "value", "equipment_id")
        for kind, value, equipment_id in rows:
            owners[(kind, value)].add(equipment_id)
    units_by_item = {item: set().union(*(owners[pair] for pair in item[0])) if item[0] else set() for item in items}
    matched_units = {next(iter(units)) for units in units_by_item.values() if len(units) == 1}
    interfaces: dict[tuple[int, str], int] = {}
    if matched_units:
        for interface_id, name, equipment_id in EquipmentInterface.objects.filter(
            equipment__in=matched_units
        ).values_list("pk", "name", "equipment"):
            interfaces[(equipment_id, name.casefold())] = interface_id
    result = {}
    for item, units in units_by_item.items():
        if len(units) == 1:
            unit = next(iter(units))
            result[item] = DeviceEquipmentMatch(unit, interfaces.get((unit, item[1].casefold())), "matched")
        elif units:
            result[item] = DeviceEquipmentMatch(None, None, "ambiguous")
        else:
            result[item] = DeviceEquipmentMatch(None, None, "unmatched")
    return result


def hardware_ids_by_equipment(*, equipment_ids: Iterable[int], computing_id: int) -> dict[int, list[HardwareIdPair]]:
    """Registered IDs of these units that are valid on ``computing_id`` (for the agent's watch list)."""
    found: dict[int, list[HardwareIdPair]] = defaultdict(list)
    for equipment_id, kind, value in (
        EquipmentHardwareId.objects.filter(_valid_for(computing_id), equipment_id__in=list(equipment_ids))
        .order_by("equipment_id", "kind", "value")
        .values_list("equipment_id", "kind", "value")
    ):
        found[equipment_id].append((kind, value))
    return dict(found)


__all__ = ("hardware_ids_by_equipment", "list_hardware_ids", "match_hardware_ids")
