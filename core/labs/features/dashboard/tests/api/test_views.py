"""Integration tests for laboratory dashboard API views."""

import uuid
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from django.utils import timezone
from rest_framework.test import APIClient

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


def make_bench(**kwargs):
    kwargs.setdefault("sku", f"B-{uuid.uuid4().hex[:10]}")
    kwargs.setdefault("name", f"Bench-{uuid.uuid4().hex[:6]}")
    return BenchFactory(**kwargs)


def make_bench_group(**kwargs):
    kwargs.setdefault("name", f"Group-{uuid.uuid4().hex[:6]}")
    return BenchGroupFactory(**kwargs)


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


@pytest.fixture()
def client_and_user(db):
    user = UserFactory()
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestDashboardOverviewAPI:
    def test_unauthenticated_returns_401_or_403(self):
        client = APIClient()
        response = client.get("/api/labs/dashboard")
        assert response.status_code in (401, 403)

    def test_authenticated_returns_paginated_envelope(self, client_and_user):
        client, _ = client_and_user
        make_bench()
        make_bench()

        response = client.get("/api/labs/dashboard")
        assert response.status_code == 200
        body = response.json()

        assert "data" in body
        assert isinstance(body["data"], list)
        assert len(body["data"]) >= 2
        assert "meta" in body
        assert "pagination" in body["meta"]
        assert body["meta"]["pagination"]["count"] >= 2

    def test_bench_item_structure_and_fields(self, client_and_user):
        client, user = client_and_user
        group = make_bench_group(description="Robotics testbeds")
        bench = make_bench(
            bench_group=group,
            lifecycle_status="available",
        )
        BenchFavorite.objects.create(user=user, bench=bench)

        response = client.get(f"/api/labs/dashboard?bench_group={group.id}")
        assert response.status_code == 200
        items = response.json()["data"]
        assert len(items) == 1

        item = items[0]
        assert item["id"] == bench.id
        assert item["name"] == bench.name
        assert item["sku"] == bench.sku
        assert item["lifecycle_status"] == "available"
        assert item["bench_group"]["id"] == group.id
        assert item["bench_group"]["name"] == group.name
        assert item["is_favorite"] is True
        assert item["current_booking"] is None
        assert item["computing"] is None
        assert item["assigned_equipment_count"] == 0

    def test_active_booking_serialized(self, client_and_user):
        client, user = client_and_user
        now = timezone.now()
        bench = make_bench()

        booking_code = f"BK-{uuid.uuid4().hex[:6]}"
        BenchBooking.objects.create(
            bench=bench,
            booking_code=booking_code,
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
            status=BookingStatus.IN_PROGRESS,
            creator=user,
        )

        response = client.get(f"/api/labs/dashboard?search={bench.sku}")
        assert response.status_code == 200
        items = response.json()["data"]
        assert len(items) >= 1
        item = next(i for i in items if i["id"] == bench.id)

        assert item["current_booking"] is not None
        assert item["current_booking"]["booking_code"] == booking_code
        assert item["current_booking"]["status"] == BookingStatus.IN_PROGRESS
        assert item["current_booking"]["user"]["id"] == user.id

    def test_computing_equipment_serialized(self, client_and_user):
        client, _ = client_and_user
        now = timezone.now()
        bench = make_bench()

        comp = ComputingEquipmentFactory(
            name=f"Host-{uuid.uuid4().hex[:4]}",
            sku=f"COMP-{uuid.uuid4().hex[:8]}",
            ip_address="192.168.1.50",
            os_name="Ubuntu 22.04 LTS",
        )
        ComputingActivity.objects.create(
            computing=comp,
            status=ComputingActivityStatus.ACTIVE,
            remote_user="dev_user",
            remote_user_display_name="Developer User",
        )
        EquipmentAssignment.objects.create(
            bench=bench,
            equipment=comp,
            assigned_at=now,
        )

        response = client.get(f"/api/labs/dashboard?search={bench.sku}")
        assert response.status_code == 200
        item = next(i for i in response.json()["data"] if i["id"] == bench.id)

        assert item["computing"] is not None
        assert item["computing"]["id"] == comp.id
        assert item["computing"]["sku"] == comp.sku
        assert item["computing"]["name"] == comp.name
        assert item["computing"]["ip_address"] == "192.168.1.50"
        assert item["computing"]["os_name"] == "Ubuntu 22.04 LTS"
        assert item["computing"]["activity_status"] == ComputingActivityStatus.ACTIVE
        assert item["computing"]["remote_user"] == "dev_user"
        assert item["computing"]["remote_user_display_name"] == "Developer User"
        assert item["samples"] == []
        assert item["licenses"] == []
        assert item["assigned_equipment_count"] == 1

    def test_dashboard_benches_samples_and_licenses_serialized(self, client_and_user):
        client, _ = client_and_user
        now = timezone.now()
        bench = make_bench()

        sample_cat = EquipmentCategoryFactory(name="Sample")
        sample_kind = EquipmentKindFactory(category=sample_cat, name="Sample DUT")
        customer = SampleCustomer.objects.create(name=f"Customer-{uuid.uuid4().hex[:6]}")
        sample = SampleEquipment.objects.create(
            name="Sample Radar v2",
            sku=f"SMP-{uuid.uuid4().hex[:6]}",
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

        comp = ComputingEquipmentFactory(name="Rig Host", sku=f"PC-{uuid.uuid4().hex[:6]}")
        EquipmentAssignment.objects.create(
            bench=bench,
            equipment=comp,
            role="Host",
            position=2,
            assigned_at=now,
        )

        lic = make_license(name="CANoe Pro 16")
        LicenseAssignment.objects.create(
            equipment=comp,
            license=lic,
            assigned_at=now,
        )

        response = client.get(f"/api/labs/dashboard?search={bench.sku}")
        assert response.status_code == 200
        item = next(i for i in response.json()["data"] if i["id"] == bench.id)

        assert item["assigned_equipment_count"] == 2
        assert len(item["samples"]) == 1
        assert item["samples"][0] == {"id": sample.id, "sku": sample.sku, "name": sample.name}

        assert len(item["licenses"]) == 1
        assert item["licenses"][0] == {"id": lic.id, "sku": lic.sku, "name": lic.name}

        assert item["computing"] is not None
        assert item["computing"]["id"] == comp.id
        assert item["computing"]["sku"] == comp.sku
        assert item["computing"]["name"] == comp.name

    def test_filter_by_bench_group(self, client_and_user):
        client, _ = client_and_user
        group_a = make_bench_group()
        group_b = make_bench_group()

        bench_a = make_bench(bench_group=group_a)
        make_bench(bench_group=group_b)

        response = client.get(f"/api/labs/dashboard?bench_group={group_a.id}")
        assert response.status_code == 200
        items = response.json()["data"]
        assert len(items) == 1
        assert items[0]["id"] == bench_a.id

    def test_filter_by_is_favorite(self, client_and_user):
        client, user = client_and_user
        fav_bench = make_bench()
        other_bench = make_bench()

        BenchFavorite.objects.create(user=user, bench=fav_bench)

        resp_fav = client.get(f"/api/labs/dashboard?is_favorite=true&search={fav_bench.sku}")
        assert resp_fav.status_code == 200
        fav_items = resp_fav.json()["data"]
        assert len(fav_items) == 1
        assert fav_items[0]["id"] == fav_bench.id

        resp_non_fav = client.get(f"/api/labs/dashboard?is_favorite=false&search={other_bench.sku}")
        assert resp_non_fav.status_code == 200
        non_fav_items = resp_non_fav.json()["data"]
        assert other_bench.id in [i["id"] for i in non_fav_items]
        assert fav_bench.id not in [i["id"] for i in non_fav_items]

    def test_filter_by_is_booked(self, client_and_user):
        client, _ = client_and_user
        now = timezone.now()
        booked = make_bench()
        free = make_bench()

        BenchBooking.objects.create(
            bench=booked,
            booking_code=f"BK-{uuid.uuid4().hex[:6]}",
            starts_at=now - timedelta(minutes=30),
            ends_at=now + timedelta(minutes=30),
            status=BookingStatus.RESERVED,
        )

        resp_booked = client.get(f"/api/labs/dashboard?is_booked=true&search={booked.sku}")
        assert resp_booked.status_code == 200
        assert [i["id"] for i in resp_booked.json()["data"]] == [booked.id]

        resp_free = client.get(f"/api/labs/dashboard?is_booked=false&search={free.sku}")
        assert resp_free.status_code == 200
        assert [i["id"] for i in resp_free.json()["data"]] == [free.id]

    def test_search_filter(self, client_and_user):
        client, _ = client_and_user
        target_name = f"Automotive CAN Bench {uuid.uuid4().hex[:6]}"
        bench_match = make_bench(name=target_name)
        other_name = f"Audio Lab {uuid.uuid4().hex[:6]}"
        make_bench(name=other_name)

        response = client.get(f"/api/labs/dashboard?search={bench_match.sku}")
        assert response.status_code == 200
        items = response.json()["data"]
        assert len(items) == 1
        assert items[0]["id"] == bench_match.id

    def test_filter_by_has_computing(self, client_and_user):
        client, _ = client_and_user
        now = timezone.now()
        bench_comp = make_bench()
        bench_plain = make_bench()

        comp = ComputingEquipmentFactory()
        EquipmentAssignment.objects.create(bench=bench_comp, equipment=comp, assigned_at=now)

        resp_with = client.get(f"/api/labs/dashboard?has_computing=true&search={bench_comp.sku}")
        assert resp_with.status_code == 200
        assert [i["id"] for i in resp_with.json()["data"]] == [bench_comp.id]

        resp_without = client.get(f"/api/labs/dashboard?has_computing=false&search={bench_plain.sku}")
        assert resp_without.status_code == 200
        assert [i["id"] for i in resp_without.json()["data"]] == [bench_plain.id]

    def test_filter_by_is_mapped(self, client_and_user):
        client, _ = client_and_user
        bench_unmapped = make_bench()
        bench_mapped = make_bench()

        from core.labs.models import Station
        station = Station.objects.create(
            name=f"Station-{uuid.uuid4().hex[:6]}",
            sku=f"ST-{uuid.uuid4().hex[:8]}",
        )
        bench_mapped.setup_location = station
        bench_mapped.save(update_fields=["setup_location"])

        resp_mapped = client.get(f"/api/labs/dashboard?is_mapped=true&search={bench_mapped.sku}")
        assert resp_mapped.status_code == 200
        assert [i["id"] for i in resp_mapped.json()["data"]] == [bench_mapped.id]

        resp_unmapped = client.get(f"/api/labs/dashboard?is_mapped=false&search={bench_unmapped.sku}")
        assert resp_unmapped.status_code == 200
        assert [i["id"] for i in resp_unmapped.json()["data"]] == [bench_unmapped.id]

    def test_unknown_query_parameter_returns_400(self, client_and_user):
        client, _ = client_and_user
        response = client.get("/api/labs/dashboard?invalid_param=123")
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "invalid_query"

    def test_query_budget_bounded(self, client_and_user, django_assert_num_queries):
        client, _ = client_and_user
        for _ in range(5):
            make_bench()

        with django_assert_num_queries(4):
            # 1: count query for pagination
            # 2: bench list query with select_related
            # 3: prefetch active bookings
            # 4: prefetch active equipment assignments
            response = client.get("/api/labs/dashboard")
            assert response.status_code == 200
            assert len(response.json()["data"]) >= 5


@pytest.mark.django_db
class TestDashboardSummaryAPI:
    def test_unauthenticated_returns_401_or_403(self):
        client = APIClient()
        response = client.get("/api/labs/dashboard/summary")
        assert response.status_code in (401, 403)

    def test_authenticated_returns_summary_metrics(self, client_and_user):
        client, user = client_and_user
        now = timezone.now()

        bench_1 = make_bench(lifecycle_status="available")
        bench_2 = make_bench(lifecycle_status="active")

        BenchFavorite.objects.create(user=user, bench=bench_1)

        BenchBooking.objects.create(
            bench=bench_2,
            booking_code=f"BK-{uuid.uuid4().hex[:6]}",
            starts_at=now - timedelta(minutes=15),
            ends_at=now + timedelta(minutes=45),
            status=BookingStatus.IN_PROGRESS,
        )

        response = client.get("/api/labs/dashboard/summary")
        assert response.status_code == 200
        body = response.json()

        assert "data" in body
        data = body["data"]
        assert data["total_benches"] >= 2
        assert data["active_bookings_count"] >= 1
        assert data["favorited_benches_count"] >= 1
        assert "available" in data["lifecycle_distribution"]
        assert "active" in data["lifecycle_distribution"]
        assert isinstance(data["utilization_rate"], float)


@pytest.mark.django_db
class TestDashboardBenchDetailAPI:
    def test_unauthenticated_returns_401_or_403(self):
        client = APIClient()
        response = client.get("/api/labs/dashboard/benches/1")
        assert response.status_code in (401, 403)

    def test_authenticated_returns_full_bench_detail(self, client_and_user):
        client, user = client_and_user
        now = timezone.now()
        bench = make_bench(description="Detailed testing rig")

        booking_code = f"BK-{uuid.uuid4().hex[:6]}"
        BenchBooking.objects.create(
            bench=bench,
            booking_code=booking_code,
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=3),
            status=BookingStatus.RESERVED,
            creator=user,
        )

        comp = ComputingEquipmentFactory(name="Rig PC", sku=f"PC-{uuid.uuid4().hex[:8]}")
        EquipmentAssignment.objects.create(
            bench=bench,
            equipment=comp,
            role="primary",
            position=1,
            assigned_at=now,
        )

        response = client.get(f"/api/labs/dashboard/benches/{bench.id}")
        assert response.status_code == 200
        data = response.json()["data"]

        assert data["id"] == bench.id
        assert data["name"] == bench.name
        assert data["description"] == "Detailed testing rig"
        assert len(data["equipment_by_category"]) == 1
        assert data["equipment_by_category"][0]["equipment"][0]["sku"] == comp.sku
        assert data["equipment_by_category"][0]["equipment"][0]["category"] == {
            "id": comp.kind.category_id,
            "name": comp.kind.category.name,
        }
        assert data["equipment_by_category"][0]["equipment"][0]["computing_activity"] == {
            "status": "offline",
            "last_agent_report_at": None,
            "is_stale": None,
        }
        assert data["equipment_by_category"][0]["equipment"][0]["licenses"] == []
        assert len(data["upcoming_bookings"]) == 1
        assert data["upcoming_bookings"][0]["booking_code"] == booking_code
        assert set(data["upcoming_bookings"][0]) == {"id", "booking_code", "starts_at", "ends_at", "status"}
        assert "user" not in data["upcoming_bookings"][0]
        assert data["current_booking"] is None
        assert data["computing"] == {
            "id": comp.id,
            "sku": comp.sku,
            "name": comp.name,
            "activity_status": "offline",
            "last_agent_report_at": None,
            "is_stale": None,
        }

    def test_category_groups_include_per_equipment_licenses_and_safe_activity(self, client_and_user):
        client, user = client_and_user
        now = timezone.now()
        bench = make_bench()
        sample_category = EquipmentCategoryFactory(name="Computing")
        sample_kind = EquipmentKindFactory(category=sample_category, name="Sample DUT")
        sample = ComputingEquipmentFactory(
            name="Mapped sample host",
            sku=f"PC-{uuid.uuid4().hex[:8]}",
            kind=sample_kind,
        )
        EquipmentAssignment.objects.create(bench=bench, equipment=sample, role="DUT", position=2, assigned_at=now)
        heartbeat = now - timedelta(minutes=11)
        ComputingActivity.objects.create(
            computing=sample,
            status=ComputingActivityStatus.ACTIVE,
            last_agent_report_at=heartbeat,
        )
        lic = make_license(name="Safe dashboard license")
        LicenseAssignment.objects.create(equipment=sample, license=lic, assigned_at=now)
        current_booking = BenchBooking.objects.create(
            bench=bench,
            booking_code=f"BK-{uuid.uuid4().hex[:6]}",
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(minutes=30),
            status=BookingStatus.IN_PROGRESS,
            creator=user,
        )
        future_booking = BenchBooking.objects.create(
            bench=bench,
            booking_code=f"BK-{uuid.uuid4().hex[:6]}",
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
            status=BookingStatus.RESERVED,
            creator=user,
        )

        response = client.get(f"/api/labs/dashboard/benches/{bench.pk}")
        assert response.status_code == 200
        groups = response.json()["data"]["equipment_by_category"]
        group = next(item for item in groups if item["id"] == sample_category.pk)
        item = group["equipment"][0]
        assert item["id"] == sample.pk
        assert item["role"] == "DUT"
        assert item["position"] == 2
        assert item["computing_activity"] == {
            "status": "active",
            "last_agent_report_at": heartbeat.isoformat().replace("+00:00", "Z"),
            "is_stale": True,
        }
        assert item["licenses"] == [{"id": lic.pk, "sku": lic.sku, "name": lic.name}]
        assert "remote_user" not in item["computing_activity"]
        assert "remote_ip" not in item["computing_activity"]
        data = response.json()["data"]
        assert data["computing"] == {
            "id": sample.id,
            "sku": sample.sku,
            "name": sample.name,
            "activity_status": ComputingActivityStatus.ACTIVE,
            "last_agent_report_at": heartbeat.isoformat().replace("+00:00", "Z"),
            "is_stale": True,
        }
        assert not {"ip_address", "rdp_file_url", "remote_user", "remote_user_display_name", "remote_ip"} & set(
            data["computing"]
        )
        assert data["current_booking"]["id"] == current_booking.pk
        assert "user" not in data["current_booking"]
        assert [item["id"] for item in data["upcoming_bookings"]] == [current_booking.pk, future_booking.pk]
        assert all("user" not in booking for booking in data["upcoming_bookings"])

        def nested_keys(value):
            if isinstance(value, dict):
                for key, nested in value.items():
                    yield key
                    yield from nested_keys(nested)
            elif isinstance(value, list):
                for nested in value:
                    yield from nested_keys(nested)

        assert not {"user", "remote_user", "ip_address", "remote_ip", "rdp_file_url"} & set(nested_keys(data))
        schema = yaml.safe_load(Path("openapi/labs-dashboard.yml").read_text(encoding="utf-8"))
        detail_schema = schema["components"]["schemas"]["DashboardBenchDetail"]["properties"]
        booking_ref = detail_schema["current_booking"]["allOf"][0]["$ref"].rsplit("/", 1)[1]
        computing_ref = detail_schema["computing"]["allOf"][0]["$ref"].rsplit("/", 1)[1]
        assert booking_ref == "DashboardBookingDetail"
        assert computing_ref == "DashboardComputingDetail"
        assert "user" not in schema["components"]["schemas"][booking_ref]["properties"]
        assert not {"ip_address", "rdp_file_url", "remote_user", "remote_user_display_name", "remote_ip"} & set(
            schema["components"]["schemas"][computing_ref]["properties"]
        )

    def test_dashboard_list_payload_remains_unchanged(self, client_and_user):
        client, user = client_and_user
        now = timezone.now()
        bench = make_bench()
        computer = ComputingEquipmentFactory(
            name="Dashboard list host",
            sku=f"PC-{uuid.uuid4().hex[:8]}",
            ip_address="192.0.2.20",
        )
        ComputingActivity.objects.create(
            computing=computer,
            status=ComputingActivityStatus.ACTIVE,
            remote_user="synthetic_user",
            remote_user_display_name="Synthetic User",
        )
        EquipmentAssignment.objects.create(bench=bench, equipment=computer, assigned_at=now)
        BenchBooking.objects.create(
            bench=bench,
            booking_code=f"BK-{uuid.uuid4().hex[:6]}",
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(minutes=20),
            status=BookingStatus.IN_PROGRESS,
            creator=user,
        )

        response = client.get(f"/api/labs/dashboard?search={bench.sku}")
        assert response.status_code == 200
        item = next(row for row in response.json()["data"] if row["id"] == bench.pk)
        assert item["computing"]["ip_address"] == "192.0.2.20"
        assert item["computing"]["remote_user"] == "synthetic_user"
        assert item["current_booking"]["user"]["id"] == user.id

    def test_nonexistent_bench_returns_404(self, client_and_user):
        client, _ = client_and_user
        response = client.get("/api/labs/dashboard/benches/999999")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "not_found"
