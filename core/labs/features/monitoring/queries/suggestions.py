"""Link suggestions from a computing unit's legacy device list (``ComputingProfile.monitored_devices``).

The old agent watched a per-computer list of Windows PnP instance IDs with labels, typed by
coordinators and never linked to inventory units. Each entry is offered as a suggestion: register
its PnP ID on the unit it names and expect that unit on this computer. Units are never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.common.domain.errors import NotFound
from core.labs.features.equipment.public import is_port_bound, match_hardware_ids, normalize_hardware_id
from core.labs.models import Equipment
from core.labs.models.monitoring import ExpectedDevice
from core.labs.models.resource.equipment.computing import ComputingProfile
from core.labs.models.resource.equipment.hardware_id import EquipmentHardwareIdKind

MAX_SUGGESTIONS = 200


@dataclass(frozen=True)
class LegacyDeviceSuggestion:
    """``status``: ``unregistered`` (no unit has the ID), ``registered`` (a unit has it but is not
    expected here), ``expected`` (done) or ``ambiguous`` (the ID is on more than one unit)."""

    pnp_id: str
    label: str
    is_port_bound: bool
    status: str
    equipment: Equipment | None
    expected_device_id: int | None


def _entries(raw: object) -> list[tuple[str, str]]:
    """``[{key: PNPDeviceID, value: label}]`` as the old agent read it; ``{id: label}`` is tolerated."""
    if isinstance(raw, dict):
        items = [{"key": key, "value": value} for key, value in raw.items()]
    elif isinstance(raw, list):
        items = [item for item in raw if isinstance(item, dict)]
    else:
        return []
    found: dict[str, str] = {}
    for item in items:
        pnp_id = normalize_hardware_id(EquipmentHardwareIdKind.PNP_ID, str(item.get("key") or ""))
        if pnp_id and len(pnp_id) <= 512 and pnp_id not in found:
            found[pnp_id] = str(item.get("value") or "").strip()[:255]
    return list(found.items())[:MAX_SUGGESTIONS]


def legacy_device_suggestions(*, computing_id: int) -> list[LegacyDeviceSuggestion]:
    profile = (
        ComputingProfile.objects.filter(equipment_id=computing_id, equipment__deleted_at__isnull=True)
        .only("equipment_id", "monitored_devices")
        .first()
    )
    if profile is None:
        raise NotFound("Computing unit not found.")
    entries = _entries(profile.monitored_devices)
    if not entries:
        return []
    evidence = {pnp_id: (((EquipmentHardwareIdKind.PNP_ID.value, pnp_id),), "") for pnp_id, _ in entries}
    matches = match_hardware_ids(computing_id=computing_id, evidence=evidence.values())
    unit_ids = {m.equipment_id for m in matches.values() if m.equipment_id}
    units = Equipment.objects.in_bulk(unit_ids)
    expected = dict(
        ExpectedDevice.objects.filter(computing_id=computing_id, equipment_id__in=unit_ids).values_list(
            "equipment_id", "pk"
        )
    )
    result = []
    for pnp_id, label in entries:
        match = matches[evidence[pnp_id]]
        unit = units.get(match.equipment_id) if match.equipment_id else None
        expected_id = expected.get(unit.pk) if unit else None
        if match.status == "ambiguous":
            status = "ambiguous"
        elif unit is None:
            status = "unregistered"
        else:
            status = "expected" if expected_id else "registered"
        result.append(
            LegacyDeviceSuggestion(
                pnp_id, label, is_port_bound(EquipmentHardwareIdKind.PNP_ID, pnp_id), status, unit, expected_id
            )
        )
    return result
