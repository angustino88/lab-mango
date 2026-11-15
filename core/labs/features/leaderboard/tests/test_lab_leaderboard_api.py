"""HTTP smoke tests: the lab leaderboard and bench profile read bench-to-equipment placements."""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.models import Bench, Equipment, EquipmentAssignment, EquipmentCategory, EquipmentKind
from tests.factories import UserFactory, grant_labs_role


@pytest.fixture()
def client(db):
    api_client = APIClient()
    api_client.force_authenticate(user=grant_labs_role(UserFactory(), "coord"))
    return api_client


@pytest.fixture()
def bench_with_equipment(db):
    bench = Bench.objects.create(sku="LB-B-1", name="Leaderboard bench")
    kind = EquipmentKind.objects.create(category=EquipmentCategory.objects.create(name="LB cat", definition="x"), name="LB kind")
    equipment = Equipment.objects.create(sku="LB-E-1", name="Leaderboard equipment", kind=kind)
    EquipmentAssignment.objects.create(
        bench=bench, equipment=equipment, role="host", position=1, assigned_at=timezone.now() - timedelta(days=1)
    )
    return bench


def test_lab_leaderboard_lists_benches_with_placed_equipment(client, bench_with_equipment):
    response = client.get("/api/labs/leaderboard/lab")

    assert response.status_code == 200, response.content


def test_bench_profile_reads_sessions_through_placed_equipment(client, bench_with_equipment):
    response = client.get(f"/api/labs/benches/{bench_with_equipment.pk}/profile")

    assert response.status_code == 200, response.content
