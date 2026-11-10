"""KPI correctness tests for analytics queries and snapshot tasks (PostgreSQL)."""
from __future__ import annotations

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.utils import timezone

from core.labs.features.analytics.application.tasks import snapshot_daily_active_benches
from core.labs.features.analytics.queries.calculations import calculate_period_trend
from core.labs.features.analytics.queries.storage import get_exceeded_storage_quotas
from core.labs.features.analytics.queries.utilization import (
    get_bench_efficiency_rankings,
    get_equipment_status_distribution,
    get_user_booking_compliance,
)
from core.labs.models import ActiveLaboratoryObservation, EquipmentStatus
from tests.factories import (
    BenchBookingFactory,
    ComputingEquipmentFactory,
    EquipmentStatusRecordFactory,
    LabSessionLogFactory,
    StorageQuotaMeasurementFactory,
)

UTC = dt_timezone.utc


class TestCalculatePeriodTrend:
    @pytest.mark.parametrize(
        ("previous", "current", "expected"),
        [
            (100, 150, 50),
            (100, 50, -50),
            (100, 100, 0),
            (0, 0, 0),
            (0, 7, 100),
            (10, 0, -100),
        ],
    )
    def test_percentage_change(self, previous, current, expected):
        assert calculate_period_trend(previous, current) == expected


@pytest.mark.django_db
class TestExceededStorageQuotas:
    def test_only_measurements_strictly_over_quota_are_returned(self):
        over = StorageQuotaMeasurementFactory(used_gibibytes=120, quota_gibibytes=100)
        StorageQuotaMeasurementFactory(used_gibibytes=80, quota_gibibytes=100)
        StorageQuotaMeasurementFactory(used_gibibytes=100, quota_gibibytes=100)
        StorageQuotaMeasurementFactory(used_gibibytes=5, quota_gibibytes=0)

        result = get_exceeded_storage_quotas()

        assert [m.pk for m in result] == [over.pk]


@pytest.mark.django_db
class TestEquipmentStatusDistribution:
    def test_counts_latest_status_per_equipment_not_every_record(self):
        equipment = ComputingEquipmentFactory()
        EquipmentStatusRecordFactory(equipment=equipment, status=EquipmentStatus.AVAILABLE)
        EquipmentStatusRecordFactory(equipment=equipment, status=EquipmentStatus.MAINTENANCE)

        counts = {row["status"]: row["count"] for row in get_equipment_status_distribution()}

        assert counts[EquipmentStatus.MAINTENANCE] == 1
        assert counts[EquipmentStatus.AVAILABLE] == 0


@pytest.mark.django_db
class TestEfficiencyBounds:
    def test_efficiency_is_capped_at_one(self):
        equipment = ComputingEquipmentFactory()
        # Monday 09:00-17:00 UTC is 8 official working hours; log a 20h active session.
        start = datetime(2024, 4, 1, 0, 0, tzinfo=UTC)
        end = datetime(2024, 4, 2, 0, 0, tzinfo=UTC)
        LabSessionLogFactory(
            computing_equipment=equipment,
            login_time=start,
            logout_time=end,
            active_duration_seconds=20 * 3600,
        )

        rows = get_bench_efficiency_rankings(from_date_time=start, to_date_time=end)

        assert rows
        assert all(0.0 <= row["efficiency"] <= 1.0 for row in rows)

    def test_compliance_is_capped_at_one(self):
        user_booking_start = timezone.now() - timedelta(hours=1)
        BenchBookingFactory(
            starts_at=user_booking_start,
            ends_at=user_booking_start + timedelta(hours=1),
        )
        LabSessionLogFactory(
            remote_user="overuser",
            login_time=user_booking_start,
            logout_time=user_booking_start + timedelta(hours=5),
            active_duration_seconds=5 * 3600,
        )

        rows = get_user_booking_compliance(
            from_date_time=user_booking_start - timedelta(hours=1),
            to_date_time=timezone.now() + timedelta(hours=1),
        )

        assert all(0.0 <= row["efficiency"] <= 1.0 for row in rows)


@pytest.mark.django_db
class TestSnapshotIdempotency:
    def test_rerun_same_day_updates_instead_of_duplicating(self):
        snapshot_daily_active_benches()
        snapshot_daily_active_benches()

        now = timezone.localtime(timezone.now())
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = ActiveLaboratoryObservation.objects.filter(period_start=start_of_day)

        assert rows.count() == 1
