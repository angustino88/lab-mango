"""Find benches by UID, SKU or name for the resource lookup."""

from core.labs.features.base.lookup import lookup_rows
from core.labs.models import Bench


def lookup_benches(*, q: str, limit: int) -> list[dict]:
    """Benches matching ``q``, retired ones included (operators look up anything they manage)."""
    rows = lookup_rows(
        Bench.objects.all(), q=q, limit=limit, fields=("setup_location__name", "setup_location__room__name")
    )
    for row in rows:
        row["context"] = " · ".join(
            name for name in (row.pop("setup_location__name"), row.pop("setup_location__room__name")) if name
        )
    return rows
