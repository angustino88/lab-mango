"""Find licenses by UID, SKU or name for the resource lookup."""

from core.labs.features.base.lookup import lookup_rows
from core.labs.models import License


def lookup_licenses(*, q: str, limit: int) -> list[dict]:
    rows = lookup_rows(License.objects.all(), q=q, limit=limit, fields=("product__name",))
    return [{**row, "context": row.pop("product__name") or ""} for row in rows]
