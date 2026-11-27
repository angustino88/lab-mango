"""GET /api/labs/bench-bookings/policy: the booking rules for the caller."""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from core.users.tests.factories import UserFactory
from tests.factories import grant_labs_role

URL = "/api/labs/bench-bookings/policy"


@pytest.mark.django_db
class TestPolicy:
    @override_settings(
        BOOKING_SLOT_WATCH_ENABLED=True, BOOKING_SLOT_WATCH_LEAD_MINUTES=20, TIME_ZONE="Asia/Ho_Chi_Minh"
    )
    def test_member_rules(self, api_client):
        response = api_client.get(URL)

        assert response.status_code == 200
        assert response["Cache-Control"] == "private, max-age=300"
        assert response.json()["data"] == {
            "time_zone": "Asia/Ho_Chi_Minh",
            "min_duration_minutes": 10,
            "start_grace_minutes": 10,
            "approval_required_above_minutes": 240,
            "max_horizon_days": None,
            "is_computing_required": True,
            "can_book_during_operator_downtime": False,
            "can_manage_others_bookings": False,
            "can_approve": False,
            "slot_watch": {"is_enabled": True, "lead_minutes": 20, "max_active": 20},
        }

    def test_coordinator_rules(self):
        client = APIClient()
        client.force_authenticate(user=grant_labs_role(UserFactory(username="policy-coordinator"), "coord"))

        data = client.get(URL).json()["data"]

        assert data["can_book_during_operator_downtime"] is True
        assert data["can_manage_others_bookings"] is True
        assert data["can_approve"] is True

    def test_anonymous_is_refused(self):
        assert APIClient().get(URL).status_code in (401, 403)
