"""Compose the owners' lookup selectors; each type is searched only if the caller may read it."""

from dataclasses import dataclass
from typing import Any

from core.labs.features.benches.public import lookup_benches
from core.labs.features.equipment.public import lookup_equipment
from core.labs.features.licenses.public import lookup_licenses
from core.labs.features.locations.public import lookup_rooms, lookup_stations
from core.users.public import LabsPermission, has_permission

RESOURCE_TYPES = ("room", "station", "bench", "equipment", "license")
MAX_PER_TYPE = 10


@dataclass(frozen=True, slots=True)
class LookupResource:
    id: int
    uid: Any
    name: str


@dataclass(frozen=True, slots=True)
class LookupMatch:
    type: str
    match: str
    resource: LookupResource
    sku: str
    context: str


def readable_types(actor: Any) -> tuple[str, ...]:
    """Lab operators read every type; everyone else none (deny by default)."""
    if has_permission(actor, LabsPermission.LAB_OPERATIONS_MANAGE):
        return RESOURCE_TYPES
    return ()


def lookup_resources(*, actor: Any, q: str, types: tuple[str, ...] = (), limit: int = 5) -> list[LookupMatch]:
    """Matches per type (at most ``limit`` each), in the order rooms, stations, benches, equipment, licenses.

    The view admits lab operators only; ``readable_types`` repeats the rule so no other caller can reach a type
    through this function. One query per searched type.
    """
    allowed = readable_types(actor)
    wanted = [kind for kind in (types or RESOURCE_TYPES) if kind in allowed]
    searches = {
        "room": lambda: lookup_rooms(q=q, limit=limit),
        "station": lambda: lookup_stations(q=q, limit=limit),
        "bench": lambda: lookup_benches(q=q, limit=limit),
        "equipment": lambda: lookup_equipment(q=q, limit=limit),
        "license": lambda: lookup_licenses(q=q, limit=limit),
    }
    matches = []
    for kind in RESOURCE_TYPES:
        if kind not in wanted:
            continue
        for row in searches[kind]():
            matches.append(
                LookupMatch(
                    type=kind,
                    match=row["match"],
                    resource=LookupResource(row["id"], row["uid"], row["name"] or row["sku"]),
                    sku=row["sku"],
                    context=row["context"],
                )
            )
    return matches
