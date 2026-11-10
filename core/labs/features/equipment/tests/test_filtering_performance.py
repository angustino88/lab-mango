"""Cardinality regressions and reproducible isolated PostgreSQL measurements."""

import json
from collections import Counter
from datetime import timedelta
from pathlib import Path
from statistics import median
from typing import Any, cast

import pytest
from django.db import connection
from django.db.models import Count, Q
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from core.common.api.filtering import Filter, FilterSpec, StrictBooleanField
from core.common.api.pagination import ResultsSetPagination
from core.labs.features.equipment.queries.equipment import list_equipment
from core.labs.features.equipment.queries.facets import EQUIPMENT_DIMENSIONS, equipment_facet_rows
from core.labs.models import (
    Bench,
    Equipment,
    EquipmentCategory,
    EquipmentKind,
    EquipmentManufacturer,
    EquipmentProductModel,
    EquipmentType,
)
from core.labs.models.resource.base.resource import Department, ResourceGroup
from core.labs.models.resource.equipment import DisplayEquipment, EquipmentInterface
from core.labs.models.resource.equipment.assignment import EquipmentAssignment

pytestmark = pytest.mark.django_db


@pytest.fixture
def cardinality_inventory():
    category = EquipmentCategory.objects.create(name="Synthetic Display", key="display", definition="Test")
    kind = EquipmentKind.objects.create(name="Synthetic kind", category=category)
    type_row = EquipmentType.objects.create(name="Synthetic type", kind=kind)
    maker = EquipmentManufacturer.objects.create(name="Synthetic maker")
    category.manufacturers.add(maker)
    product = EquipmentProductModel.objects.create(
        name="Synthetic product", manufacturer=maker, equipment_type=type_row
    )
    EquipmentManufacturer.objects.filter(pk=maker.pk).update(active=False)
    department = Department.objects.create(name="Synthetic department", active=False)
    group = ResourceGroup.objects.create(name="Synthetic group", department=department, active=False)
    display = DisplayEquipment.objects.create(
        sku="SYN-DISPLAY",
        name="Synthetic match",
        kind=kind,
        type=type_row,
        manufacturer=maker,
        product_model=product,
        department=department,
        group=group,
    )
    display.interfaces.add(*(EquipmentInterface.objects.create(name=f"Synthetic HDMI {i}") for i in range(3)))
    null = Equipment.objects.create(sku="SYN-NULL", name="Synthetic null", kind=kind)
    deleted = Equipment.objects.create(
        sku="SYN-DELETED", name="Synthetic deleted", kind=kind, deleted_at=timezone.now()
    )
    bench = Bench.objects.create(sku="SYN-BENCH", name="Synthetic bench")
    now = timezone.now()
    EquipmentAssignment.objects.bulk_create(
        [
            EquipmentAssignment(
                equipment=display,
                bench=bench,
                role=f"history-{i}",
                assigned_at=now - timedelta(days=10 + i),
                unassigned_at=now - timedelta(days=i + 1),
            )
            for i in range(3)
        ]
    )
    EquipmentAssignment.objects.create(equipment=display, bench=bench, assigned_at=now)
    return display, null, deleted


def assert_single_valued_path(path: str) -> None:
    model: Any = Equipment
    for segment in path.split("__"):
        field = model._meta.get_field(segment)
        assert not field.one_to_many and not field.many_to_many, path
        if field.is_relation:
            assert field.many_to_one or field.one_to_one, path
            model = field.related_model


def test_all_dimension_paths_are_single_valued():
    assert len(EQUIPMENT_DIMENSIONS) == 7
    for dimension in EQUIPMENT_DIMENSIONS.values():
        assert_single_valued_path(dimension.id_path)
        assert_single_valued_path(dimension.name_path)
    # Ensure the guard rejects a real multiplying relation, not a vacuous check.
    with pytest.raises(AssertionError):
        assert_single_valued_path("bench_assignments__role")


@pytest.mark.parametrize("dimension", tuple(EQUIPMENT_DIMENSIONS))
@pytest.mark.parametrize("membership", ["all", "reverse", "m2m"])
def test_facet_membership_isolation(cardinality_inventory, dimension, membership, django_assert_num_queries):
    display, null, deleted = cardinality_inventory
    if membership == "m2m":
        population = DisplayEquipment.objects.filter(interfaces__name__icontains="HDMI")
        assert population.count() == 3
        expected_ids = [display.pk]
    elif membership == "reverse":
        population = Equipment.objects.filter(bench_assignments__role__startswith="history-")
        assert population.count() == 3
        expected_ids = [display.pk]
    else:
        population = Equipment.objects.all()  # outer deletion guard must still apply
        expected_ids = [display.pk, null.pk]
    configured = EQUIPMENT_DIMENSIONS[dimension]
    expected = Counter(Equipment.objects.filter(pk__in=expected_ids).values_list(configured.id_path, flat=True))
    rows = equipment_facet_rows(population=population, dimension=dimension)
    assert cast(Any, rows.query.annotations["equipment_count"]).distinct is False
    with django_assert_num_queries(1):
        actual = list(rows)
    assert {row["facet_id"]: row["equipment_count"] for row in actual} == expected
    # Compare against the previous aggregate on the same isolated membership.
    legacy = rows.annotate(equipment_count=Count("pk", distinct=True))
    assert actual == list(legacy)


@pytest.mark.parametrize("values,expected_count", [({}, 2), ({"history": "history-"}, 1), ({"q": "history-"}, 1)])
def test_reverse_filter_search_and_previous_distinct(cardinality_inventory, values, expected_count):
    spec = FilterSpec(
        [Filter("history", serializers.CharField(), "bench_assignments__role__startswith", "text", distinct=True)],
        search_fields=("bench_assignments__role",),
        search_distinct=True,
    )
    base = Equipment.objects.filter(deleted_at__isnull=True)
    result = spec.apply(base, values)
    assert result.query.distinct == bool(values)
    assert result.count() == expected_count
    assert spec.apply(base.distinct(), {}).query.distinct
    assert spec.apply(base.distinct(), {}).count() == 2


def test_m2m_filter_and_separate_reverse_filter_calls(cardinality_inventory):
    display = cardinality_inventory[0]
    spec = FilterSpec(
        [Filter("interface", serializers.CharField(), "interfaces__name__icontains", "text", distinct=True)]
    )
    assert list(spec.apply(DisplayEquipment.objects.all(), {"interface": "HDMI"}).values_list("pk", flat=True)) == [
        display.pk
    ]
    separate = FilterSpec(
        [
            Filter("first", serializers.CharField(), "bench_assignments__role", "text", distinct=True),
            Filter("second", serializers.CharField(), "bench_assignments__role", "text", distinct=True),
        ]
    )
    result = separate.apply(Equipment.objects.all(), {"first": "history-0", "second": "history-1"})
    assert list(result.values_list("pk", flat=True)) == [display.pk]
    # Combining these filters into one call would incorrectly require one related row to match both.
    assert not Equipment.objects.filter(
        Q(bench_assignments__role="history-0") & Q(bench_assignments__role="history-1")
    ).exists()


@pytest.mark.parametrize(
    "filters",
    [
        {},
        {"status": "available"},
        {"status": "in_use"},
        {"status": "broken"},
        {"assigned": True},
        {"assigned": False},
        {"search": "Synthetic"},
        {"search": "maker"},
        {"search": "product"},
        {"kind": 0},
    ],
)
def test_generic_list_count_page_annotation_parity(cardinality_inventory, filters, django_assert_max_num_queries):
    if "kind" in filters:
        filters = {"kind": cardinality_inventory[0].kind_id}
    rows = list_equipment(**filters)
    # Outer joins must remain FK/one-to-one; EXISTS/scalar subqueries cannot fan out.
    str(rows.query)
    for join in rows.query.alias_map.values():
        field = getattr(join, "join_field", None)
        if field is not None:
            assert not field.one_to_many and not field.many_to_many
    legacy = rows.distinct()
    assert rows.count() == legacy.count()
    # 1 for the page, plus the placement, loan and upcoming-reservation prefetches when the page has rows.
    with django_assert_max_num_queries(4):
        page = list(rows[:25])
    old_page = list(legacy[:25])
    assert [row.pk for row in page] == [row.pk for row in old_page]
    assert len({row.pk for row in page}) == len(page)
    annotations = (
        "display_status",
        "acquisition_price",
        "acquisition_currency",
        "has_active_assignment",
    )
    assert [tuple(getattr(row, name) for name in annotations) for row in page] == [
        tuple(getattr(row, name) for name in annotations) for row in old_page
    ]


def test_generic_list_does_not_request_distinct(cardinality_inventory):
    assert list_equipment().query.distinct is False


def test_latest_history_and_false_assignment_membership(cardinality_inventory):
    display, null, deleted = cardinality_inventory
    assert list(list_equipment(status="broken").values_list("pk", flat=True)) == []
    assert list(list_equipment(status="in_use").values_list("pk", flat=True)) == [display.pk]
    assert list(list_equipment(status="available").values_list("pk", flat=True)) == [null.pk]
    assert list(list_equipment(assigned=False).values_list("pk", flat=True)) == [null.pk]
    assert list(list_equipment(assigned=True).values_list("pk", flat=True)) == [display.pk]
    references = {
        "category": display.kind.category_id,
        "kind": display.kind_id,
        "equipment_type": display.type_id,
        "manufacturer": display.manufacturer_id,
    }
    for name, value in references.items():
        queryset = list_equipment(**{name: value})
        assert list(queryset.values_list("pk", flat=True)) == list(queryset.distinct().values_list("pk", flat=True))
        assert display.pk in queryset.values_list("pk", flat=True)


def measure_synthetic_explain_capture(cardinality_inventory):
    """Run on the explicitly isolated cluster only; persist measured SQL/JSON evidence."""
    assert connection.vendor == "postgresql"
    assert connection.settings_dict["HOST"] == "127.0.0.1"
    assert str(connection.settings_dict["PORT"]) == "55439"
    assert connection.settings_dict["NAME"] == "test_filtering_perf"
    display, null, deleted = cardinality_inventory
    kind = display.kind
    Equipment.objects.bulk_create(
        [
            Equipment(
                sku=f"SYN-PERF-{i:05d}",
                name=f"Synthetic inventory {i % 80:03d}",
                kind=kind,
                manufacturer_id=display.manufacturer_id if i % 4 else None,
                product_model_id=display.product_model_id if i % 4 else None,
                type_id=display.type_id if i % 4 else None,
                department_id=display.department_id if i % 4 else None,
                group_id=display.group_id if i % 4 else None,
            )
            for i in range(1600)
        ]
    )
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE")
    base = list_equipment()
    spec = FilterSpec([Filter("unused", StrictBooleanField(), "calibration_required", "boolean", distinct=True)])
    cases = {
        "generic": base,
        "generic_search": list_equipment(search="inventory"),
        "generic_status": list_equipment(status="available"),
        "generic_unassigned": list_equipment(assigned=False),
        "shared_absent": spec.apply(Equipment.objects.filter(deleted_at__isnull=True).order_by("pk"), {}),
        **{f"facet_{key}": equipment_facet_rows(population=base, dimension=key) for key in EQUIPMENT_DIMENSIONS},
        "facet_m2m": equipment_facet_rows(
            population=DisplayEquipment.objects.filter(interfaces__name__icontains="HDMI"), dimension="kind"
        ),
    }
    evidence: dict[str, Any] = {
        "inventory_rows": 1603,
        "repeats": 7,
        "cache": "one warm-up, then seven alternating count/page executions",
        "cases": {},
    }
    request = Request(APIRequestFactory().get("/synthetic", {"page_size": 25}))
    for name, queryset in cases.items():
        paginator = ResultsSetPagination()
        with CaptureQueriesContext(connection) as captured:
            page = paginator.paginate_queryset(queryset, request)
        assert page is not None and paginator.page is not None
        assert len(captured) == 2
        samples: dict[str, list[float]] = {"count": [], "page": []}
        plans = {}
        for repeat in range(8):
            for label, query in zip(("count", "page"), captured.captured_queries, strict=True):
                with connection.cursor() as cursor:
                    cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query["sql"])
                    plan = cursor.fetchone()[0][0]
                if repeat:
                    samples[label].append(plan["Execution Time"])
                plans[label] = plan
        evidence["cases"][name] = {
            "count": paginator.page.paginator.count,
            "page_ids": [row["facet_id"] if isinstance(row, dict) else row.pk for row in page],
            "page_keys": [row["facet_name"] if isinstance(row, dict) else row.sku for row in page],
            "sql": {
                label: query["sql"] for label, query in zip(("count", "page"), captured.captured_queries, strict=True)
            },
            "execution_ms": samples,
            "median_ms": {label: median(values) for label, values in samples.items()},
            "last_plans": plans,
        }
    stage = "before" if base.query.distinct else "after"
    artifact = Path(__file__).parents[1] / "docs" / f"filtering-performance-{stage}.json"
    artifact.write_text(json.dumps(evidence, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"Evidence: {artifact.name}; 1603 rows; 7 measured repeats per count/page")
    for name, result in evidence["cases"].items():
        print(name, result["median_ms"])
