"""Find rooms by UID, SKU or name for the resource lookup."""

from core.labs.features.base.lookup import lookup_rows
from core.labs.models import Room


def lookup_rooms(*, q: str, limit: int) -> list[dict]:
    return [{**row, "context": ""} for row in lookup_rows(Room.objects.all(), q=q, limit=limit)]
