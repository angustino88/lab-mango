"""Bounded inventory matching; capability names never identify a physical asset."""

from collections import defaultdict

from core.labs.features.equipment.contracts import DeviceEquipmentMatch
from core.labs.models import Equipment, EquipmentInterface


def match_observed_devices(evidence: tuple[tuple[str, str], ...]) -> dict[tuple[str, str], DeviceEquipmentMatch]:
    """At most 200 evidence pairs; return ambiguity rather than choose an arbitrary serial match.

    Only active (not soft-deleted) inventory is a candidate. One joined query fetches at
    most 4001 rows; a saturated batch is conservatively ambiguous, keeping pathological
    inventories bounded.
    """
    if len(evidence) > 200:
        raise ValueError("At most 200 device records are supported.")
    serials = {serial for serial, _ in evidence if serial}
    # A bounded candidate query per batch, not per observation. Cap the global result
    # and fail closed if saturated; no unbounded inventory materialization.
    rows = list(
        Equipment.objects.filter(serial_number__in=serials, deleted_at__isnull=True)
        .values("pk", "serial_number", "interfaces__id", "interfaces__name")
        .order_by("pk", "interfaces__id")[:4001]
    )
    saturated = len(rows) > 4000
    candidates: dict[str, dict[int, dict[str, set[int]]]] = defaultdict(dict)
    for row in rows:
        interfaces = candidates[row["serial_number"]].setdefault(row["pk"], {})
        if row["interfaces__name"]:
            interfaces.setdefault(row["interfaces__name"].casefold(), set()).add(row["interfaces__id"])
    result = {}
    for serial, interface_name in evidence:
        units = candidates[serial] if serial else {}
        compatible = [
            (pk, interface_id)
            for pk, names in units.items()
            for interface_id in names.get(interface_name.casefold(), ())
        ]
        if saturated or len(compatible) > 1:
            match = DeviceEquipmentMatch(None, None, "ambiguous")
        elif len(compatible) == 1:
            match = DeviceEquipmentMatch(*compatible[0], "matched")
        elif units:
            match = DeviceEquipmentMatch(None, None, "interface_mismatch")
        else:
            match = DeviceEquipmentMatch(None, None, "unmatched")
        result[(serial, interface_name)] = match
    return result


def monitoring_interfaces() -> tuple[str, ...]:
    """Bounded catalog hint; does not claim the agent has a collector for each name."""
    return tuple(EquipmentInterface.objects.order_by("name", "pk").values_list("name", flat=True)[:200])
