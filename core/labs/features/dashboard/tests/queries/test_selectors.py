"""Unit tests for dashboard query selectors."""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from core.labs.features.dashboard.exceptions import DashboardResourceNotFound
from core.labs.features.dashboard.queries.selectors import (
    get_dashboard_bench_detail,
    get_dashboard_summary,
    list_dashboard_benches,
)
from core.labs.models import (
    BenchBooking,
    BenchFavorite,
    BookingStatus,
    ComputingActivity,
    ComputingActivityStatus,
    LicenseAssignment,
)
from core.labs.models.resource.equipment.assignment import EquipmentAssignment
from core.labs.models.resource.equipment.sample import SampleCustomer, SampleEquipment
from core.labs.models.resource.license.license import (
    License,
    LicenseCategory,
    LicenseProduct,
    LicenseType,
    LicenseVendor,
)
from tests.factories import (
    BenchFactory,
    BenchGroupFactory,
    ComputingEquipmentFactory,
    EquipmentCategoryFactory,
    EquipmentKindFactory,
    UserFactory,
)


def make_license(**kwargs):
    kwargs.setdefault("sku", f"LIC-{uuid.uuid4().hex[:6]}")
    kwargs.setdefault("name", f"License-{uuid.uuid4().hex[:4]}")
    if "product" not in kwargs:
        kwargs["product"] = LicenseProduct.objects.create(name=f"Product-{uuid.uuid4().hex[:6]}")
    if "vendor" not in kwargs:
        kwargs["vendor"] = LicenseVendor.objects.create(name=f"Vendor-{uuid.uuid4().hex[:6]}")
    if "type" not in kwargs:
        kwargs["type"] = LicenseType.objects.create(name=f"Type-{uuid.uuid4().hex[:6]}")
    if "category" not in kwargs:
        kwargs["category"] = LicenseCategory.objects.create(name=f"Category-{uuid.uuid4().hex[:6]}")
    return License.objects.create(**kwargs)


@pytest.mark.django_db
class TestListDashboardBenches:
    def test_returns_non_deleted_benches_ordered_by_name(self):
        bench_b = BenchFactory(name="Beta Bench", sku="B-002")
        bench_a = BenchFactory(name="Alpha Bench", sku="B-001")
        bench_del = BenchFactory(name="Deleted Bench", sku="B-003", deleted_at=timezone.now())

        results = list(list_dashboard_benches())
        ids = [b.id for b in results]

        assert ids == [bench_a.id, bench_b.id]
        assert bench_del.id not in ids

    def test_filter_by_bench_group(self):
        group_1 = BenchGroupFactory(name="RF Lab")
        group_2 = BenchGroupFactory(name="Optics Lab")

        bench_1 = BenchFactory(bench_group=group_1)
        bench_2 = BenchFactory(bench_group=group_2)

        results = list(list_dashboard_benches(bench_group=group_1.id))
        ids = [b.id for b in results]

        assert ids == [bench_1.id]
        assert bench_2.id not in ids

    def test_filter_by_lifecycle_status(self):
        bench_avail = BenchFactory(lifecycle_status="in_service")
        bench_maint = BenchFactory(lifecycle_status="out_of_service")

        results = list(list_dashboard_benches(lifecycle_status="in_service"))
        ids = [b.id for b in results]

        assert bench_avail.id in ids
        assert bench_maint.id not in ids

    def test_filter_by_is_favorite(self):
        user = UserFactory()
        fav_bench = BenchFactory()
        other_bench = BenchFactory()

        BenchFavorite.objects.create(user=user, bench=fav_bench)

        fav_results = list(list_dashboard_benches(actor=user, is_favorite=True))
        assert [b.id for b in fav_results] == [fav_bench.id]

        non_fav_results = list(list_dashboard_benches(actor=user, is_favorite=False))
        assert other_bench.id in [b.id for b in non_fav_results]
        assert fav_bench.id not in [b.id for b in non_fav_results]

    def test_filter_by_is_booked(self):
        now = timezone.now()
        booked_bench = BenchFactory()
        free_bench = BenchFactory()

        BenchBooking.objects.create(
            bench=booked_bench,
            booking_code="BK-ACTIVE-01",
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(hours=1),
            status=BookingStatus.IN_PROGRESS,
        )

        booked_results = list(list_dashboard_benches(is_booked=True))
        assert booked_bench.id in [b.id for b in booked_results]
        assert free_bench.id not in [b.id for b in booked_results]

        free_results = list(list_dashboard_benches(is_booked=False))
        assert free_bench.id in [b.id for b in free_results]
        assert booked_bench.id not in [b.id for b in free_results]

    def test_search_filters_by_name_and_sku(self):
        bench_target = BenchFactory(name="Spectrum Analyzer Bench", sku="SKU-SPEC-001")
        bench_other = BenchFactory(name="General Workstation", sku="SKU-GEN-002")

        results = list(list_dashboard_benches(search="spectrum"))
        ids = [b.id for b in results]

        assert ids == [bench_target.id]
        assert bench_other.id not in ids

    def test_list_dashboard_benches_prefetches_samples_and_licenses(self):
        now = timezone.now()
        bench = BenchFactory()

        sample_cat = EquipmentCategoryFactory(name="Sample")
        sample_kind = EquipmentKindFactory(category=sample_cat, name="Sample Kind")
        customer = SampleCustomer.objects.create(name="Acme Corp")
        sample = SampleEquipment.objects.create(
            name="Sample Radar",
            sku="SMP-RADAR-01",
            customer=customer,
            kind=sample_kind,
        )
        EquipmentAssignment.objects.create(
            bench=bench,
            equipment=sample,
            role="DUT",
            position=1,
            assigned_at=now,
        )

        comp = ComputingEquipmentFactory(name="Host Rig", sku="PC-RIG-01")
        EquipmentAssignment.objects.create(
            bench=bench,
            equipment=comp,
            role="Host",
            position=2,
            assigned_at=now,
        )
        lic = make_license(name="CANoe Pro")
        LicenseAssignment.objects.create(
            equipment=comp,
            license=lic,
            assigned_at=now,
        )

        results = list(list_dashboard_benches(search=bench.sku))
        assert len(results) == 1
        fetched = results[0]
        assignments = getattr(fetched, "_active_equipment_assignments", [])
        assert len(assignments) == 2

        eq_map = {a.equipment.sku: a.equipment for a in assignments}
        assert hasattr(eq_map["SMP-RADAR-01"], "sampleequipment")
        assert hasattr(eq_map["PC-RIG-01"], "computingequipment")

        comp_eq = eq_map["PC-RIG-01"]
        lic_assignments = getattr(comp_eq, "_active_license_assignments", [])
        assert len(lic_assignments) == 1
        assert lic_assignments[0].license.name == "CANoe Pro"


@pytest.mark.django_db
class TestGetDashboardSummary:
    def test_summary_aggregates_metrics_correctly(self):
        now = timezone.now()
        user = UserFactory()

        bench_1 = BenchFactory(lifecycle_status="in_service")
        bench_2 = BenchFactory(lifecycle_status="in_service")
        BenchFactory(lifecycle_status="out_of_service")

        BenchFavorite.objects.create(user=user, bench=bench_1)

        BenchBooking.objects.create(
            bench=bench_2,
            booking_code="BK-DASH-SUM-01",
            starts_at=now - timedelta(minutes=30),
            ends_at=now + timedelta(minutes=30),
            status=BookingStatus.IN_PROGRESS,
        )

        comp = ComputingEquipmentFactory(
            name="Host 1",
            sku="COMP-001",
            os_name="Linux",
        )
        ComputingActivity.objects.create(
            computing=comp,
            status=ComputingActivityStatus.ACTIVE,
            remote_user="engineer_1",
        )
        EquipmentAssignment.objects.create(
            bench=bench_2,
            equipment=comp,
            assigned_at=now,
        )

        summary = get_dashboard_summary(actor=user)

        assert summary["total_benches"] == 3
        assert summary["active_bookings_count"] == 1
        assert summary["favorited_benches_count"] == 1
        # Four stored values (redesign step 5); "active" is computed from bookings, not stored.
        assert summary["lifecycle_distribution"] == {"planned": 0, "in_service": 2, "out_of_service": 1, "retired": 0}
        assert summary["activity_distribution"][ComputingActivityStatus.ACTIVE] == 1
        assert summary["utilization_rate"] == round((1 / 3) * 100.0, 2)


@pytest.mark.django_db
class TestGetDashboardBenchDetail:
    def test_retrieves_bench_detail_with_assignments_and_bookings(self):
        now = timezone.now()
        bench = BenchFactory(name="Detail Target Bench", description="High-performance bench")

        booking = BenchBooking.objects.create(
            bench=bench,
            booking_code="BK-UPCOMING-01",
            starts_at=now + timedelta(hours=2),
            ends_at=now + timedelta(hours=4),
            status=BookingStatus.RESERVED,
        )

        comp = ComputingEquipmentFactory(
            name="Attached PC",
            sku="PC-DETAIL-01",
            os_name="Windows 11",
        )
        EquipmentAssignment.objects.create(
            bench=bench,
            equipment=comp,
            role="primary",
            position=1,
            assigned_at=now,
        )

        detail = get_dashboard_bench_detail(bench.id)

        assert detail.id == bench.id
        assert detail.name == "Detail Target Bench"
        assert len(getattr(detail, "_upcoming_bookings", [])) == 1
        assert getattr(detail, "_upcoming_bookings")[0].id == booking.id
        assert len(getattr(detail, "_active_equipment_assignments", [])) == 1

    def test_raises_resource_not_found_for_missing_bench(self):
        with pytest.raises(DashboardResourceNotFound):
            get_dashboard_bench_detail(999999)
