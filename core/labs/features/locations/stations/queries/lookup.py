"""Find stations by UID, SKU or name for the resource lookup."""

from core.labs.features.base.lookup import lookup_rows
from core.labs.models import Station


def lookup_stations(*, q: str, limit: int) -> list[dict]:
    rows = lookup_rows(Station.objects.all(), q=q, limit=limit, fields=("room__name",))
    return [{**row, "context": row.pop("room__name") or ""} for row in rows]
