"""Deliberate read composition boundary for the approved enriched bench GET.

Centralized assignment models supply the existing bench setup projection;
live activity and reservation rules are accessed only through owner facades.
Authenticated readers retain the existing unrestricted bench visibility.
"""

from datetime import datetime
from typing import Any

from django.core.paginator import Paginator

from core.labs.features.bench_bookings.public import bench_booking_summary
from core.labs.features.equipment.public import computing_activity_projection
from core.labs.models import Bench

from .selectors import get_bench, list_bench_equipment


def get_bench_detail(
    *,
    bench_id: int,
    actor: Any,
    evaluated_at: datetime,
    equipment_page: int = 1,
    equipment_page_size: int = 20,
) -> Bench:
    """One request timestamp, bounded equipment and bookings, no writes/locks."""
    bench = get_bench(bench_id=bench_id, actor=actor)
    page = Paginator(list_bench_equipment(bench_id=bench_id), equipment_page_size).page(equipment_page)
    assignments = list(page.object_list)
    activity = computing_activity_projection(
        equipment_ids=[assignment.equipment_id for assignment in assignments],
        evaluated_at=evaluated_at,
    )
    for assignment in assignments:
        assignment.computing_activity = activity.get(assignment.equipment_id)
    page.object_list = assignments
    bench.equipment_page = page
    bench.booking_summary = bench_booking_summary(bench_id=bench_id, evaluated_at=evaluated_at)
    return bench
