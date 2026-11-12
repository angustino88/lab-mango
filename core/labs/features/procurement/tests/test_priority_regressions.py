"""Regressions: purchase priority options and priority validation returned 500 (undefined names)."""

import pytest
from rest_framework.test import APIClient

from core.labs.features.procurement.api.serializers import DraftLineInputSerializer
from core.labs.models import PurchasePriority
from tests.factories import UserFactory, grant_labs_role

pytestmark = pytest.mark.django_db


def test_priority_options_return_active_priorities():
    PurchasePriority.objects.create(code="reg-normal", name="Regression normal", rank=1, is_active=True)
    PurchasePriority.objects.create(code="reg-old", name="Regression old", rank=2, is_active=False)
    client = APIClient()
    client.force_authenticate(user=grant_labs_role(UserFactory(username="priority-coordinator"), "coord"))

    response = client.get("/api/labs/purchase-priorities")

    assert response.status_code == 200, response.content
    codes = {item["code"] for item in response.json()["data"]}
    assert "reg-normal" in codes and "reg-old" not in codes


def test_inactive_priority_is_a_validation_error_not_a_crash():
    retired = PurchasePriority.objects.create(code="reg-retired", name="Regression retired", rank=3, is_active=False)
    serializer = DraftLineInputSerializer(
        data={"description": "Cable", "quantity": 1, "unit_price": "1.00", "priority_id": retired.pk}
    )

    assert not serializer.is_valid()
    assert "priority_id" in serializer.errors
