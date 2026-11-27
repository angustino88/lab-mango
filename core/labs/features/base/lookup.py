"""Rank resources by how well a short text matches their UID, SKU or name. One query per call."""

import uuid
from typing import Any

from django.db.models import Case, IntegerField, Q, QuerySet, Value, When

MATCH_UID = "uid_exact"
MATCH_SKU = "sku_exact"
MATCH_NAME = "name_exact"
MATCH_PREFIX = "prefix"
MATCH_CONTAINS = "contains"
MATCH_ORDER = (MATCH_UID, MATCH_SKU, MATCH_NAME, MATCH_PREFIX, MATCH_CONTAINS)


def lookup_rows(queryset: QuerySet, *, q: str, limit: int, fields: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Rows of ``queryset`` matching ``q``, best match first: exact UID, exact SKU, exact name, prefix, contains.

    Each row has ``id``, ``uid``, ``sku``, ``name``, ``match`` and the extra ``fields`` (``values()`` paths).
    """
    text = q.strip()
    matches = Q(sku__icontains=text) | Q(name__icontains=text)
    ranks = []
    try:
        uid = uuid.UUID(text)
    except ValueError:
        uid = None
    if uid is not None:
        matches |= Q(uid=uid)
        ranks.append(When(uid=uid, then=Value(0)))
    ranks += [
        When(sku__iexact=text, then=Value(1)),
        When(name__iexact=text, then=Value(2)),
        When(Q(sku__istartswith=text) | Q(name__istartswith=text), then=Value(3)),
    ]
    rows = (
        queryset.filter(matches)
        .annotate(lookup_rank=Case(*ranks, default=Value(4), output_field=IntegerField()))
        .order_by("lookup_rank", "name", "pk")
        .values("id", "uid", "sku", "name", "lookup_rank", *fields)[:limit]
    )
    return [{**row, "match": MATCH_ORDER[row.pop("lookup_rank")]} for row in rows]
