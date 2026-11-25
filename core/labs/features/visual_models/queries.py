from typing import Any, cast

from django.db.models import Count, IntegerField, Model, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from core.labs.models.visual_models import VisualModelAsset

from .contracts import ModelSelection
from .targets import TARGETS


def _usage():
    """Resources referencing the asset, as one correlated count per referencing table (no join fan-out)."""
    total: Any = Value(0)
    for relation in VisualModelAsset._meta.related_objects:
        field = relation.field.name
        related = cast("type[Model]", relation.related_model)
        counts = (
            related._base_manager.filter(**{field: OuterRef("pk")})
            .order_by()
            .values(field)
            .annotate(total=Count("pk"))
            .values("total")
        )
        total = total + Coalesce(Subquery(counts, output_field=IntegerField()), 0)
    return total


def list_assets():
    return VisualModelAsset.objects.annotate(usage_count=_usage())


def get_asset(asset_id: int):
    return list_assets().filter(pk=asset_id).first()


def asset_usage(asset_id: int) -> int:
    row = list_assets().filter(pk=asset_id).values("usage_count").first()
    return row["usage_count"] if row else 0


def _selection_rows(segment: str):
    target = TARGETS[segment]
    source_lookups = [(name, lookup) for name, lookup in target.inherits]
    return (
        target.queryset()
        .annotate(selection_name=target.name(), effective_visual_model_id=target.effective())
        .values(
            "id",
            "selection_name",
            "visual_model_id",
            "effective_visual_model_id",
            *(lookup for _, lookup in source_lookups),
        )
        .order_by("selection_name", "id")
    )


def _shape(segment: str, row) -> ModelSelection:
    origin: str | None = None
    if row["visual_model_id"] is not None:
        origin = "own"
    else:
        origin = next((name for name, lookup in TARGETS[segment].inherits if row[lookup] is not None), None)
    return ModelSelection(
        id=row["id"],
        name=row["selection_name"] or "",
        visual_model_id=row["visual_model_id"],
        effective_visual_model_id=row["effective_visual_model_id"],
        origin=origin,
    )


class SelectionList:
    """Lazy, sliceable list of selections so the shared paginator can count and slice it in SQL."""

    def __init__(self, segment: str):
        self.segment = segment
        self.rows = _selection_rows(segment)

    def count(self) -> int:
        return self.rows.count()

    def __len__(self) -> int:
        return self.count()

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [_shape(self.segment, row) for row in self.rows[index]]
        return _shape(self.segment, self.rows[index])


def list_selections(segment: str) -> SelectionList:
    return SelectionList(segment)


def get_selection(segment: str, pk: int) -> ModelSelection | None:
    row = _selection_rows(segment).filter(pk=pk).first()
    return _shape(segment, row) if row else None


def effective_visual_models(segment: str, ids) -> dict[int, int | None]:
    """The model each resource shows after inheriting catalog defaults, for the room mapping."""
    if not ids:
        return {}
    target = TARGETS[segment]
    rows = target.queryset().filter(pk__in=ids).annotate(effective=target.effective()).values_list("id", "effective")
    return dict(rows)
