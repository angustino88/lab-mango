"""Approved GET-only bounded bench detail contract (synthetic PostgreSQL data)."""

from datetime import datetime, timedelta, timezone

import pytest
from django.contrib.auth import get_user_model
from django.core.paginator import EmptyPage
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from core.labs.features.benches.api.serializers import BenchDetailSerializer, BenchSerializer
from core.labs.models import Bench, BenchBooking, ComputingActivity, Equipment, EquipmentAssignment
from core.labs.models.booking.reference_data import LabProject
from core.labs.models.resource.equipment.reference_data import EquipmentCategory, EquipmentKind
from tests.factories import create_computing_equipment, grant_labs_role

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


@pytest.fixture()
def detail(monkeypatch, settings):
    from core.labs.features.benches.api import views

    monkeypatch.setattr(views.timezone, "now", lambda: NOW)
    settings.ROOT_URLCONF = "core.labs.features.benches.tests.detail_urls"
    # API-only harness: force_authenticate does not exercise allauth middleware.
    settings.MIDDLEWARE = [item for item in settings.MIDDLEWARE if not item.startswith("allauth.")]
    owner = get_user_model().objects.create_user(username="detail-owner", email="owner@example.test")
    reader = get_user_model().objects.create_user(username="detail-reader", email="reader@example.test")
    bench = Bench.objects.create(sku="DETAIL-BENCH", name="Detail bench", owner=owner)
    client = APIClient()
    grant_labs_role(reader, "coord")
    client.force_authenticate(reader)
    client._test_user = reader
    return client, bench


def assign(bench, index, *, computing=False, **kwargs):
    category, _ = EquipmentCategory.objects.get_or_create(
        name="Computing" if computing else "Laboratory",
        defaults={"definition": "Synthetic test category"},
    )
    kind, _ = EquipmentKind.objects.get_or_create(category=category, name="Synthetic kind")
    create = create_computing_equipment if computing else Equipment.objects.create
    equipment = create(sku=f"DETAIL-EQ-{index}", name=f"Equipment {index}", kind=kind, **kwargs)
    return EquipmentAssignment.objects.create(
        bench=bench,
        equipment=equipment,
        position=index,
        assigned_at=NOW - timedelta(days=1),
        monitor=True,
    )


def reserve(bench, index, *, start=-1, end=1, status="reserved", approval="approved", project=None):
    return BenchBooking.objects.create(
        bench=bench,
        booking_code=f"DETAIL-BOOK-{index}",
        starts_at=NOW + timedelta(hours=start),
        ends_at=NOW + timedelta(hours=end),
        status=status,
        approval_status=approval,
        project=project,
        # The database requires reasons for cancelled and rejected bookings.
        cancellation_reason="Cancelled in test setup" if status == "cancelled" else "",
        rejection_reason="Rejected in test setup" if approval == "rejected" else "",
    )


def read_projection(detail, query=None):
    client, bench = detail
    from core.labs.features.benches.queries.detail import get_bench_detail

    response = get_bench_detail(
        bench_id=bench.pk,
        actor=client._test_user,
        evaluated_at=NOW,
        **(query or {}),
    )
    return BenchDetailSerializer(response).data


def test_empty_detail_projection_preserves_fields_and_adds_bounded_shapes(detail):
    data = read_projection(detail)
    assert set(data) == set(BenchSerializer.Meta.fields) | {"equipment", "booking_summary"}
    assert data["equipment_url"] == f"/api/labs/benches/{detail[1].pk}/equipment"
    assert data["equipment"] == {
        "data": [],
        "meta": {
            "pagination": {
                "count": 0,
                "page": 1,
                "page_size": 20,
                "next": None,
                "previous": None,
            }
        },
    }
    assert data["booking_summary"] == {
        "evaluated_at": "2026-10-20T12:00:00Z",
        "current_reservations": [],
        "current_reservations_count": 0,
        "is_current_reservations_complete": True,
        "next_reservation": None,
    }


def test_pages_preserve_assignment_fields_and_computing_projection(detail):
    _, bench = detail
    first = assign(bench, 0)
    second = assign(bench, 1, computing=True)
    data = read_projection(detail, {"equipment_page_size": 1})
    equipment = data["equipment"]
    row = equipment["data"][0]
    assert set(row) == {"id", "equipment", "role", "position", "is_monitored", "assigned_at", "computing_activity"}
    assert row["id"] == first.pk
    assert row["computing_activity"] is None
    assert row["is_monitored"] is True
    link = equipment["meta"]["pagination"]["next"]
    assert link.startswith(f"/api/labs/benches/{bench.pk}?")
    assert second.pk not in [row["id"] for row in equipment["data"]]


def test_default_and_maximum_page_sizes_and_out_of_range(detail):
    for index in range(21):
        assign(detail[1], index)
    assert len(read_projection(detail)["equipment"]["data"]) == 20
    assert len(read_projection(detail, {"equipment_page_size": 100})["equipment"]["data"]) == 21
    with pytest.raises(EmptyPage):
        read_projection(detail, {"equipment_page": 3})


def test_freshness_boundaries_multiple_computers_and_no_writes(detail):
    _, bench = detail
    for index, heartbeat in enumerate(
        [None, NOW - timedelta(minutes=10), NOW - timedelta(minutes=10, microseconds=1)]
    ):
        assignment = assign(bench, index, computing=True)
        ComputingActivity.objects.create(
            computing_id=assignment.equipment_id,
            status="free",
            last_agent_report_at=heartbeat,
            remote_user="synthetic-private-user",
            remote_computer="synthetic-private-host",
        )
    assign(bench, 3, computing=True)
    with CaptureQueriesContext(connection) as queries:
        data = read_projection(detail)
    rows = data["equipment"]["data"]
    assert [row["computing_activity"]["is_stale"] for row in rows] == [None, False, True, None]
    assert [row["computing_activity"]["status"]["value"] for row in rows] == ["free", "free", "free", "offline"]
    assert ComputingActivity.objects.count() == 3
    assert not any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries)
    activity_sql = [q["sql"] for q in queries if "labs_computingactivity" in q["sql"]]
    assert len(activity_sql) == 1
    assert not any(
        field in activity_sql[0] for field in ("remote_user", "remote_ip", "inactive_at", "remote_computer")
    )
    bench.refresh_from_db()
    assert bench.modified == bench.created


def test_booking_temporal_approval_boundaries_and_minimal_projection(detail):
    _, bench = detail
    project = LabProject.objects.create(project_name="Synthetic project")
    current = reserve(bench, 1, start=0, approval="pending", project=project)
    reserve(bench, 2, start=-2, end=0)
    reserve(bench, 3, status="completed")
    reserve(bench, 4, approval="rejected")
    future = reserve(bench, 5, start=1, end=2, approval="pending")
    reserve(bench, 6, start=2, end=3)
    with CaptureQueriesContext(connection) as queries:
        summary = read_projection(detail)["booking_summary"]
    assert [row["id"] for row in summary["current_reservations"]] == [current.pk]
    row = summary["current_reservations"][0]
    assert set(row) == {"id", "booking_code", "starts_at", "ends_at", "status", "approval_status", "project"}
    assert row["project"] == {"id": project.pk, "name": "Synthetic project"}
    assert row["approval_status"] == {"value": "pending", "label": "Pending"}
    assert summary["next_reservation"]["id"] == future.pk
    sql = [q["sql"] for q in queries if "labs_benchbooking" in q["sql"]]
    assert not any(field in " ".join(sql) for field in ("reason", "approved_by", "remote_user"))


def test_current_bookings_cap_count_and_deterministic_order(detail, monkeypatch):
    mock_summary = {
        "evaluated_at": NOW,
        "current_reservations": [
            {
                "id": i,
                "booking_code": f"DETAIL-BOOK-{i}",
                "starts_at": NOW - timedelta(hours=1),
                "ends_at": NOW + timedelta(hours=1),
                "status": {"value": "in_progress" if i % 2 else "reserved", "label": "Status"},
                "approval_status": {"value": "approved", "label": "Approved"},
                "project": None,
            }
            for i in range(1, 6)
        ],
        "current_reservations_count": 7,
        "is_current_reservations_complete": False,
        "next_reservation": None,
    }
    monkeypatch.setattr("core.labs.features.benches.queries.detail.bench_booking_summary", lambda **kwargs: mock_summary)
    summary = read_projection(detail)["booking_summary"]
    assert summary["current_reservations_count"] == 7
    assert summary["is_current_reservations_complete"] is False
    assert [row["id"] for row in summary["current_reservations"]] == [1, 2, 3, 4, 5]


def test_exactly_five_current_bookings_are_complete(detail, monkeypatch):
    mock_summary = {
        "evaluated_at": NOW,
        "current_reservations": [
            {
                "id": i,
                "booking_code": f"DETAIL-BOOK-{i}",
                "starts_at": NOW - timedelta(hours=1),
                "ends_at": NOW + timedelta(hours=1),
                "status": {"value": "reserved", "label": "Reserved"},
                "approval_status": {"value": "approved", "label": "Approved"},
                "project": None,
            }
            for i in range(1, 6)
        ],
        "current_reservations_count": 5,
        "is_current_reservations_complete": True,
        "next_reservation": None,
    }
    monkeypatch.setattr("core.labs.features.benches.queries.detail.bench_booking_summary", lambda **kwargs: mock_summary)
    summary = read_projection(detail)["booking_summary"]
    assert summary["current_reservations_count"] == 5
    assert summary["is_current_reservations_complete"] is True
    assert [row["id"] for row in summary["current_reservations"]] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize("status", ["cancelled", "expired"])
def test_cancelled_and_expired_bookings_excluded_from_current_and_next(detail, status):
    reserve(detail[1], 0, status=status)
    reserve(detail[1], 1, start=1, end=2, status=status)
    summary = read_projection(detail)["booking_summary"]
    assert summary["current_reservations"] == []
    assert summary["current_reservations_count"] == 0
    assert summary["is_current_reservations_complete"] is True
    assert summary["next_reservation"] is None


def test_other_bench_equipment_and_bookings_do_not_leak(detail):
    other = Bench.objects.create(sku="OTHER-BENCH", name="Other bench")
    own = assign(detail[1], 0, computing=True)
    foreign = assign(other, 1, computing=True)
    ComputingActivity.objects.create(computing_id=foreign.equipment_id, status="busy")
    current = reserve(detail[1], 0)
    next_booking = reserve(detail[1], 1, start=2, end=3)
    reserve(other, 2)
    reserve(other, 3, start=1, end=2)
    data = read_projection(detail)
    assert data["equipment_count"] == 1
    assert data["equipment"]["meta"]["pagination"]["count"] == 1
    assert [row["id"] for row in data["equipment"]["data"]] == [own.pk]
    assert data["equipment"]["data"][0]["computing_activity"]["status"]["value"] == "offline"
    summary = data["booking_summary"]
    assert summary["current_reservations_count"] == 1
    assert [row["id"] for row in summary["current_reservations"]] == [current.pk]
    assert summary["next_reservation"]["id"] == next_booking.pk


def test_full_hundred_of_101_computers_within_query_budget(detail, django_assert_max_num_queries):
    assignments = [assign(detail[1], index, computing=True) for index in range(101)]
    ComputingActivity.objects.bulk_create(
        [
            ComputingActivity(computing_id=item.equipment_id, status="free", last_agent_report_at=NOW)
            for item in assignments
        ]
    )
    with django_assert_max_num_queries(7):
        data = read_projection(detail, {"equipment_page_size": 100})
    equipment = data["equipment"]
    assert len(equipment["data"]) == 100
    assert [row["id"] for row in equipment["data"]] == [item.pk for item in assignments[:100]]
    assert all(row["computing_activity"]["is_stale"] is False for row in equipment["data"])
    assert equipment["meta"]["pagination"]["count"] == 101
    assert equipment["meta"]["pagination"]["page_size"] == 100
    assert equipment["meta"]["pagination"]["next"] is not None


def test_deleted_unassigned_equipment_is_excluded_from_internal_projection(detail):
    live = assign(detail[1], 0)
    gone = assign(detail[1], 1)
    Equipment.objects.filter(pk=gone.equipment_id).update(deleted_at=NOW)
    old = assign(detail[1], 2)
    EquipmentAssignment.objects.filter(pk=old.pk).update(unassigned_at=NOW)
    data = read_projection(detail)
    assert data["equipment_count"] == 1
    assert [row["id"] for row in data["equipment"]["data"]] == [live.pk]


def test_enriched_projection_remains_an_internal_projection(detail):
    _, bench = detail
    assert set(read_projection(detail)) == set(BenchSerializer.Meta.fields) | {"equipment", "booking_summary"}
    assert bench.pk == detail[1].pk


def test_query_count_does_not_grow_with_page_rows(detail, django_assert_max_num_queries):
    for index in range(20):
        assign(detail[1], index, computing=True)
    for index in range(6):
        reserve(detail[1], index, start=index * 2, end=index * 2 + 1)
    with django_assert_max_num_queries(7):
        assert len(read_projection(detail)["equipment"]["data"]) == 20


def test_composition_uses_only_owner_public_read_facades():
    import ast
    from pathlib import Path

    tree = ast.parse(Path("core/labs/features/benches/queries/detail.py").read_text(encoding="utf-8"))
    other_feature_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith(
            (
                "core.labs.features.equipment",
                "core.labs.features.bench_bookings",
            )
        )
    }
    assert other_feature_imports == {
        "core.labs.features.equipment.public",
        "core.labs.features.bench_bookings.public",
    }


def test_enriched_projection_remains_internal_and_list_write_unchanged(detail):

    client, bench = detail

    assert APIClient().get(f"/api/labs/benches/{bench.pk}").status_code == 401

    assert set(read_projection(detail)) == set(BenchSerializer.Meta.fields) | {"equipment", "booking_summary"}

    listed = client.get("/api/labs/benches").data["data"][0]
    assert listed["sku"] == bench.sku
