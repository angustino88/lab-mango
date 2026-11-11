"""POST /agent/bookings/actions/validate and the paths GET /agent/info publishes."""

import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from core.agents.tests.api.test_agent_request_signature import _clear_nonce_cache, enrolled  # noqa: F401
from core.agents.tests.signing import signed_headers
from core.labs.models import Bench, BenchBooking, BookingStatus, EquipmentAssignment

PATH = "/agent/bookings/actions/validate"
CHECK_IN_PATH = "/agent/bookings/actions/check-in"


def validate(identity, key, payload, *, path=PATH):
    body = json.dumps(payload).encode()
    client = APIClient()
    client.credentials(**signed_headers(key, identity.agent_uid, body, method="POST", path=path))
    return client.post(path, data=body, content_type="application/json")


def check_in(identity, key, payload):
    return validate(identity, key, payload, path=CHECK_IN_PATH)


@pytest.fixture()
def placed(enrolled):  # noqa: F811
    """The enrolled agent's computer on bench A, plus bench B and a user who books."""
    identity, key, _ = enrolled
    bench = Bench.objects.create(sku="VAL-BENCH-A", name="Bench A")
    other_bench = Bench.objects.create(sku="VAL-BENCH-B", name="Bench B")
    EquipmentAssignment.objects.create(
        equipment=identity.equipment, bench=bench, assigned_at=timezone.now() - timedelta(days=1)
    )
    user = get_user_model().objects.create_user(username="booker", password="unused")
    return identity, key, bench, other_bench, user


def make_booking(user, bench, code, *, status=BookingStatus.RESERVED, start=-timedelta(minutes=1)):
    now = timezone.now()
    booking = BenchBooking(
        bench=bench,
        starts_at=now + start,
        ends_at=now + start + timedelta(hours=1),
        status=status,
        booking_code=code,
        cancellation_reason="Cancelled in test setup" if status == BookingStatus.CANCELLED else "",
    )
    booking.save(actor=user)
    return booking


def test_eligible_booking_returns_its_window(placed):
    identity, key, bench, _, user = placed
    booking = make_booking(user, bench, "BK-OK")

    response = validate(identity, key, {"booking_code": "BK-OK"})

    assert response.status_code == 200, response.json()
    data = response.json()["data"]
    assert data["eligible"] is True
    assert data["booking_code"] == "BK-OK" and data["booked_for"] == "booker"
    assert data["starts_at"] and data["ends_at"]
    booking.refresh_from_db()
    assert booking.status == BookingStatus.RESERVED  # read-only: no check-in


def test_every_failure_gets_the_same_answer(placed):
    identity, key, bench, other_bench, user = placed
    make_booking(user, other_bench, "BK-OTHER-BENCH")
    make_booking(user, bench, "BK-CANCELLED", status=BookingStatus.CANCELLED)
    make_booking(user, bench, "BK-LATER", start=timedelta(hours=1))

    bodies = [
        validate(identity, key, {"booking_code": code}).json()
        for code in ("BK-UNKNOWN", "BK-OTHER-BENCH", "BK-CANCELLED", "BK-LATER")
    ]

    assert all(body == bodies[0] for body in bodies)
    assert bodies[0] == {"data": {"eligible": False}}


@pytest.mark.parametrize("payload", [{"booking_code": ""}, {}, {"booking_code": "x" * 65}])
def test_invalid_code_is_rejected(placed, payload):
    identity, key, *_ = placed

    assert validate(identity, key, payload).status_code == 422


def test_request_cannot_name_a_bench_or_computer(placed):
    identity, key, bench, _, user = placed
    make_booking(user, bench, "BK-OK")

    response = validate(identity, key, {"booking_code": "BK-OK", "bench_id": bench.pk})

    assert response.status_code == 422


@pytest.mark.django_db
def test_unsigned_request_is_rejected():
    response = APIClient().post(PATH, data={"booking_code": "BK-OK"}, format="json")

    assert response.status_code == 401


def test_info_publishes_session_and_validation_paths(db):
    data = APIClient().get("/agent/info").json()["data"]

    assert {"session_logs", "booking_validation", "booking_check_in"} <= set(data["capabilities"])
    assert data["endpoints"] == {
        "session_logs": "/agent/session-logs",
        "booking_validation": "/agent/bookings/actions/validate",
        "booking_check_in": "/agent/bookings/actions/check-in",
    }


def test_check_in_starts_the_booking(placed):
    identity, key, bench, _, user = placed
    booking = make_booking(user, bench, "BK-IN")

    response = check_in(identity, key, {"booking_code": "BK-IN"})

    assert response.status_code == 200, response.json()
    data = response.json()["data"]
    assert data["checked_in"] is True and data["booking_code"] == "BK-IN" and data["booked_for"] == "booker"
    booking.refresh_from_db()
    assert booking.status == BookingStatus.IN_PROGRESS
    assert check_in(identity, key, {"booking_code": "BK-IN"}).json()["data"]["checked_in"] is True


def test_check_in_failures_get_the_same_answer(placed):
    identity, key, bench, other_bench, user = placed
    make_booking(user, other_bench, "BK-OTHER-BENCH")
    make_booking(user, bench, "BK-CANCELLED", status=BookingStatus.CANCELLED)
    later = make_booking(user, bench, "BK-LATER", start=timedelta(hours=1))

    bodies = [
        check_in(identity, key, {"booking_code": code}).json()
        for code in ("BK-UNKNOWN", "BK-OTHER-BENCH", "BK-CANCELLED", "BK-LATER")
    ]

    assert all(body == {"data": {"checked_in": False}} for body in bodies)
    later.refresh_from_db()
    assert later.status == BookingStatus.RESERVED


@pytest.mark.parametrize("payload", [{"booking_code": ""}, {}, {"booking_code": "BK-IN", "bench_id": 1}])
def test_check_in_rejects_invalid_requests(placed, payload):
    identity, key, *_ = placed

    assert check_in(identity, key, payload).status_code == 422


@pytest.mark.django_db
def test_unsigned_check_in_is_rejected():
    assert APIClient().post(CHECK_IN_PATH, data={"booking_code": "BK-IN"}, format="json").status_code == 401
