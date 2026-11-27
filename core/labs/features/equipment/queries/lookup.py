"""Find equipment by UID, SKU or name for the resource lookup, with where it is now."""

from django.db.models import OuterRef, Subquery

from core.labs.features.base.lookup import lookup_rows
from core.labs.models import Equipment, EquipmentAssignment


def lookup_equipment(*, q: str, limit: int) -> list[dict]:
    """Context is the current placement: bench, else station, else room, else the location note."""
    current = EquipmentAssignment.objects.filter(equipment_id=OuterRef("pk"), unassigned_at__isnull=True).order_by(
        "-assigned_at", "-pk"
    )
    queryset = Equipment.objects.annotate(
        placed_bench=Subquery(current.values("bench__name")[:1]),
        placed_station=Subquery(current.values("station__name")[:1]),
        placed_room=Subquery(current.values("room__name")[:1]),
        placed_note=Subquery(current.values("location_note")[:1]),
    )
    rows = lookup_rows(
        queryset, q=q, limit=limit, fields=("placed_bench", "placed_station", "placed_room", "placed_note")
    )
    for row in rows:
        places = [row.pop(key) for key in ("placed_bench", "placed_station", "placed_room", "placed_note")]
        row["context"] = next((place for place in places if place), "")
    return rows
