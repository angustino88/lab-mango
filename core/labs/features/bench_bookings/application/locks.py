"""Row locks that serialize bench booking writes per bench."""

from collections.abc import Iterable

from django.core.exceptions import ValidationError

from core.labs.models import Bench


def lock_benches(bench_ids: Iterable[int]) -> dict[int, Bench]:
    """Lock benches in primary-key order so concurrent writers acquire locks consistently."""
    ids = sorted(set(bench_ids))
    benches = {bench.pk: bench for bench in Bench.all_objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    if benches.keys() != set(ids):
        raise ValidationError({"bench": "Select an existing bench."})
    return benches
