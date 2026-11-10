"""Bounded resource-only projections, owned by equipment; no remote identity columns."""

from datetime import datetime, timedelta

from django.db.models import F

from core.labs.models import ComputingActivity, ComputingActivityStatus

from ..contracts import InactiveEquipmentSnapshot


def inactive_equipment_candidates(
    *, now: datetime, after_id: int = 0, limit: int = 100, equipment_id: int | None = None
) -> list[InactiveEquipmentSnapshot]:
    rows = ComputingActivity.objects.filter(
        computing_id__gt=after_id,
        computing__deleted_at__isnull=True,
        status=ComputingActivityStatus.INACTIVE,
        last_agent_report_at__gte=now - timedelta(minutes=10),
        last_agent_report_at__lte=now,
        inactive_at__lt=now - timedelta(minutes=60),
        computing__bench_assignments__unassigned_at__isnull=True,
        # Join-based lookups bypass the bench-only manager; rooms and stations are not benches.
        computing__bench_assignments__bench__isnull=False,
        computing__bench_assignments__assigned_at__lte=F("inactive_at"),
    ).exclude(booking_code="")
    if equipment_id is not None:
        rows = rows.filter(computing_id=equipment_id)
    return [
        InactiveEquipmentSnapshot(
            equipment_id=row["computing_id"],
            bench_id=row["computing__bench_assignments__bench_id"],
            booking_code=row["booking_code"],
            inactive_at=row["inactive_at"],
            assigned_at=row["computing__bench_assignments__assigned_at"],
            bench_name=row["computing__bench_assignments__bench__name"]
            or row["computing__bench_assignments__bench__sku"],
            equipment_name=row["computing__name"] or row["computing__sku"],
        )
        for row in rows.order_by("computing_id").values(
            "computing_id",
            "computing__bench_assignments__bench_id",
            "booking_code",
            "inactive_at",
            "computing__bench_assignments__assigned_at",
            "computing__bench_assignments__bench__name",
            "computing__bench_assignments__bench__sku",
            "computing__name",
            "computing__sku",
        )[: min(max(limit, 1), 100)]
        if row["inactive_at"] is not None
    ]
