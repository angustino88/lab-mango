"""Seed a bookable stub lab: benches, computers placed on them, and a project.

Runs inside Django with the same guard as the identity stubs (``ENTRA_STUB_ISSUER_ENABLED`` in DEBUG) and
touches only ``STUB-`` rows. Placement goes through ``core.labs`` ``place_equipment`` (equipment lock plus
``one_active_bench_per_equipment``); labs has no public command for creating equipment or projects, so
those rows are created the way ``tests/factories.py`` creates them. Bookings are never created here: a stub
user books through the API (``python -m tools.stubs scenario book``), as ADR 004 requires.

    python -m tools.stubs lab seed             # safe to rerun
    python -m tools.stubs lab list             # stub key -> id, uid (equipment UIDs feed agent provision)
    python -m tools.stubs lab clear-bookings   # delete bookings on STUB benches so scenarios start clean
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.stubs.common import LAB_FILE
from tools.stubs.identities import setup_django

SKU_PREFIX = "STUB-"
CATEGORY_KEY = "stub-computing"


@dataclass(frozen=True, slots=True)
class LabRow:
    kind: str  # bench | computing | project
    key: str
    id: int
    uid: str | None
    detail: str


def _sku(key: str) -> str:
    return f"{SKU_PREFIX}{key.upper()}"


def require_stub_mode() -> None:
    from core.users.public import stub_tenant_id

    stub_tenant_id()  # raises StubIdentitiesDisabled outside local stub mode


def seed(path: Path = LAB_FILE) -> list[tuple[str, bool]]:
    """Create missing stub lab rows and placements. Returns (stub key, created or changed)."""
    from django.db import transaction

    from core.labs.features.equipment.public import (
        PlaceEquipmentInput,
        active_equipment_bench_assignment,
        place_equipment,
    )
    from core.labs.models import Bench, Equipment, EquipmentCategory, EquipmentKind, LabProject
    from core.labs.models.resource.equipment.computing import ComputingProfile

    require_stub_mode()
    spec = json.loads(path.read_text())
    outcomes: list[tuple[str, bool]] = []
    with transaction.atomic():
        category, _ = EquipmentCategory.objects.get_or_create(
            key=CATEGORY_KEY,
            defaults={"name": "STUB Computing", "definition": "Stub computers for local tests", "monitored": True},
        )
        kind, _ = EquipmentKind.objects.get_or_create(category=category, name="STUB Computer")
        benches = {}
        for item in spec.get("benches", []):
            bench, created = Bench.objects.get_or_create(sku=_sku(item["key"]), defaults={"name": item["name"]})
            benches[item["key"]] = bench
            outcomes.append((item["key"], created))
        for item in spec.get("projects", []):
            _, created = LabProject.objects.get_or_create(
                code=_sku(item["key"]), defaults={"project_name": item["name"], "active": True}
            )
            outcomes.append((item["key"], created))
        for item in spec.get("computing", []):
            equipment = Equipment.objects.filter(sku=_sku(item["key"]), deleted_at__isnull=True).first()
            created = equipment is None
            if equipment is None:
                equipment = Equipment.objects.create(sku=_sku(item["key"]), name=item["name"], kind=kind)
            ComputingProfile.objects.get_or_create(equipment=equipment, defaults={"os_name": "Stub OS"})
            changed = created
            bench_key = item.get("bench")
            if bench_key is not None:
                bench = benches[bench_key]
                placement = active_equipment_bench_assignment(equipment_id=equipment.pk)
                if placement is None or placement.bench_id != bench.pk:
                    place_equipment(PlaceEquipmentInput(equipment_id=equipment.pk, bench_id=bench.pk), actor=None)
                    changed = True
            outcomes.append((item["key"], changed))
    return outcomes


def rows(path: Path = LAB_FILE) -> list[LabRow]:
    from core.labs.models import Bench, Equipment, LabProject

    require_stub_mode()
    spec = json.loads(path.read_text())
    result = []
    for item in spec.get("benches", []):
        bench = Bench.objects.filter(sku=_sku(item["key"])).values_list("pk", "uid").first()
        if bench:
            result.append(LabRow("bench", item["key"], bench[0], str(bench[1]), item["name"]))
    for item in spec.get("computing", []):
        equipment = (
            Equipment.objects.filter(sku=_sku(item["key"]), deleted_at__isnull=True).values_list("pk", "uid").first()
        )
        if equipment:
            result.append(LabRow("computing", item["key"], equipment[0], str(equipment[1]), item.get("bench") or "-"))
    for item in spec.get("projects", []):
        project = LabProject.objects.filter(code=_sku(item["key"])).values_list("pk", flat=True).first()
        if project:
            result.append(LabRow("project", item["key"], project, None, item["name"]))
    return result


def clear_bookings() -> int:
    """Delete bookings on stub benches (stub data only) so scenarios start from a free calendar."""
    from core.labs.models import BenchBooking

    require_stub_mode()
    deleted, _ = BenchBooking.objects.filter(bench__sku__startswith=SKU_PREFIX).delete()
    return deleted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.stubs lab", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed")
    list_parser = commands.add_parser("list")
    list_parser.add_argument("--json", action="store_true", help="machine-readable output")
    commands.add_parser("clear-bookings")
    args = parser.parse_args(argv)

    setup_django()
    from core.users.public import StubIdentitiesDisabled

    try:
        if args.command == "seed":
            for key, changed in seed():
                print(f"{'changed  ' if changed else 'unchanged'} {key}")
        elif args.command == "list":
            found = rows()
            if args.json:
                print(json.dumps([_as_dict(row) for row in found], indent=2))
            else:
                for row in found:
                    print(f"{row.kind:<9} {row.key:<10} id={row.id:<5} uid={row.uid or '-':<36} {row.detail}")
        elif args.command == "clear-bookings":
            print(f"deleted {clear_bookings()} rows")
    except StubIdentitiesDisabled as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


def _as_dict(row: LabRow) -> dict:
    return {"kind": row.kind, "key": row.key, "id": row.id, "uid": row.uid, "detail": row.detail}


if __name__ == "__main__":
    sys.exit(main())
