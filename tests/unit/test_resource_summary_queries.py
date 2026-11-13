"""PostgreSQL checks for current status, deleted scope and query budgets."""

import pytest
from django.utils import timezone

from core.labs.features.benches.queries.summaries import get_bench_status_summary
from core.labs.features.equipment.queries.summaries import (
    get_computing_activity_summary,
    get_equipment_category_status_summary,
    get_equipment_status_summary,
)
from core.labs.models import ComputingActivity, Equipment
from tests.factories import BenchFactory, ComputingEquipmentFactory, set_condition


@pytest.mark.django_db
def test_current_equipment_display_status_and_deleted_inventory(django_assert_num_queries):
    equipment = ComputingEquipmentFactory()
    set_condition(equipment, "out_of_service")
    deleted = ComputingEquipmentFactory()
    Equipment.objects.filter(pk=deleted.pk).update(deleted_at=timezone.now())
    with django_assert_num_queries(1):
        summary = get_equipment_status_summary()
    counts = {item["status"]["value"]: item["resource_count"] for item in summary["statuses"]}
    assert summary["total_count"] == 1
    assert counts["broken"] == 1
    assert counts["available"] == 0


@pytest.mark.django_db
def test_computing_activity_includes_unassigned_and_missing_telemetry(django_assert_num_queries):
    active = ComputingEquipmentFactory()
    ComputingEquipmentFactory()
    ComputingActivity.objects.create(computing=active, status="active")
    with django_assert_num_queries(1):
        summary = get_computing_activity_summary()
    assert summary["total_count"] == 2
    assert summary["unknown_status_count"] == 1
    assert next(row for row in summary["statuses"] if row["status"]["value"] == "active")["resource_count"] == 1


@pytest.mark.django_db
def test_computing_category_summary_counts_only_computing_equipment(django_assert_num_queries):
    computing = ComputingEquipmentFactory()
    set_condition(ComputingEquipmentFactory(), "out_of_service")
    with django_assert_num_queries(1):
        summary = get_equipment_category_status_summary(category_id=computing.kind.category_id)
    counts = {item["status"]["value"]: item["resource_count"] for item in summary["statuses"]}
    assert summary["total_count"] == 2
    assert counts["available"] == 1
    assert counts["broken"] == 1


@pytest.mark.django_db
def test_bench_lifecycle_is_not_activity_or_booking(django_assert_num_queries):
    BenchFactory(lifecycle_status="in_service")
    with django_assert_num_queries(1):
        summary = get_bench_status_summary()
    assert summary["total_count"] == 1
    assert summary["unknown_status_count"] == 0
