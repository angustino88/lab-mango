"""Find benches by UID, SKU or name for the resource lookup."""

from core.labs.features.base.lookup import lookup_rows
from core.labs.models import Bench, ResourceLifecycleStatus


def lookup_benches(*, q: str, limit: int, bookable_only: bool) -> list[dict]:
    """Benches matching ``q``; ``bookable_only`` keeps in-service benches (what every Labs role may book)."""
    queryset = Bench.objects.all()
    if bookable_only:
        queryset = queryset.filter(lifecycle_status=ResourceLifecycleStatus.IN_SERVICE)
    rows = lookup_rows(queryset, q=q, limit=limit, fields=("setup_location__name", "setup_location__room__name"))
    for row in rows:
        row["context"] = " · ".join(
            name for name in (row.pop("setup_location__name"), row.pop("setup_location__room__name")) if name
        )
    return rows
