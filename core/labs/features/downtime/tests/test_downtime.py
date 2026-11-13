"""Downtime windows, the computed state they drive, and the booking rules they enforce.

Design: docs/proposals/resource-status-and-downtime.md (rules 1-5, RS3, RS4).
"""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.bench_bookings.exceptions import BenchBookingConflict
from core.labs.features.bench_bookings.public import CreateBenchBookingInput, create_bench_booking
from core.labs.models import (
    Bench,
    BenchBooking,
    BookingStatus,
    ResourceDowntime,
    Room,
    Station,
    StationType,
)
from core.users.models import User
from tests.factories import grant_labs_role

URL = "/api/labs/downtimes"


@pytest.fixture
def coordinator(db):
    return grant_labs_role(User.objects.create_user(username="downtime-coord", display_name="Coord"), "coord")


@pytest.fixture
def client(coordinator):
    result = APIClient()
    result.force_authenticate(coordinator)
    return result


@pytest.fixture
def room(db):
    return Room.objects.create(name="R101", sku="R101")


@pytest.fixture
def station(room):
    return Station.objects.create(name="ST-01", sku="ST-01", room=room, type=StationType.objects.create(name="Desk"))


@pytest.fixture
def bench(station):
    return Bench.objects.create(name="B-Radar-01", sku="B-RADAR-01", setup_location=station)


def _window(hours_from_now=1, hours=2):
    starts_at = timezone.now() + timedelta(hours=hours_from_now)
    return starts_at, starts_at + timedelta(hours=hours)


def _book(bench, actor, starts_at, ends_at):
    return create_bench_booking(
        actor=actor, data=CreateBenchBookingInput(bench_id=bench.pk, starts_at=starts_at, ends_at=ends_at)
    )


def _schedule(client, resource_type, resource_id, starts_at=None, ends_at=None, **extra):
    payload = {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "condition": "in_maintenance",
        "reason": "maintenance",
        **extra,
    }
    if starts_at is not None:
        payload["starts_at"] = starts_at.isoformat()
    if ends_at is not None:
        payload["ends_at"] = ends_at.isoformat()
    return client.post(URL, payload, format="json")


@pytest.mark.django_db
def test_room_downtime_passes_down_to_bench_and_blocks_new_bookings(client, coordinator, room, bench):
    starts_at, ends_at = _window()

    created = _schedule(client, "room", room.pk, starts_at, ends_at)

    assert created.status_code == 201, created.data
    assert created.data["data"]["resource"] == {"type": "room", "id": room.pk}
    assert created.data["data"]["kind"]["value"] == "planned"
    assert created.data["data"]["state"] == "scheduled"
    with pytest.raises(BenchBookingConflict, match="Room is in maintenance"):
        _book(bench, coordinator, starts_at + timedelta(minutes=30), ends_at + timedelta(hours=1))
    # Outside the window the bench is free.
    _book(bench, coordinator, ends_at, ends_at + timedelta(hours=1))


@pytest.mark.django_db
def test_overlapping_bookings_are_refused_unless_cancellation_is_confirmed(client, coordinator, room, bench):
    starts_at, ends_at = _window()
    booking = _book(bench, coordinator, starts_at, ends_at)

    refused = _schedule(client, "station", bench.setup_location_id, starts_at, ends_at)

    assert refused.status_code == 409, refused.data
    assert refused.data["error"]["code"] == "downtime_booking_conflict"
    assert str(booking.pk) in str(refused.data["error"]["details"])
    assert not ResourceDowntime.objects.exists()

    confirmed = _schedule(
        client, "station", bench.setup_location_id, starts_at, ends_at, cancel_conflicting_bookings=True
    )

    assert confirmed.status_code == 201, confirmed.data
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED
    assert "maintenance" in booking.cancellation_reason


@pytest.mark.django_db
def test_same_resource_windows_cannot_overlap(client, bench):
    starts_at, ends_at = _window()
    assert _schedule(client, "bench", bench.pk, starts_at, ends_at).status_code == 201

    again = _schedule(client, "bench", bench.pk, starts_at + timedelta(minutes=10), ends_at)

    assert again.status_code == 409, again.data
    assert again.data["error"]["code"] == "downtime_overlap"


@pytest.mark.django_db
def test_downtime_needs_an_in_service_resource(client, bench):
    Bench.objects.filter(pk=bench.pk).update(lifecycle_status="planned")

    response = _schedule(client, "bench", bench.pk)

    assert response.status_code == 409, response.data
    assert response.data["error"]["code"] == "downtime_not_allowed"


@pytest.mark.django_db
def test_end_and_cancel_follow_the_window_state_and_are_idempotent(client, bench):
    current = _schedule(client, "bench", bench.pk).data["data"]
    later_start, later_end = _window(hours_from_now=24)
    later = _schedule(client, "station", bench.setup_location_id, later_start, later_end).data["data"]

    assert client.post(f"{URL}/{current['id']}/actions/cancel").data["error"]["code"] == "downtime_not_allowed"
    assert client.post(f"{URL}/{later['id']}/actions/end").data["error"]["code"] == "downtime_not_allowed"

    ended = client.post(f"{URL}/{current['id']}/actions/end")
    ended_again = client.post(f"{URL}/{current['id']}/actions/end")
    cancelled = client.post(f"{URL}/{later['id']}/actions/cancel")
    cancelled_again = client.post(f"{URL}/{later['id']}/actions/cancel")

    assert (ended.status_code, ended.data["data"]["state"]) == (200, "ended")
    assert ended_again.data["data"]["ends_at"] == ended.data["data"]["ends_at"]
    assert (cancelled.status_code, cancelled.data["data"]["state"]) == (200, "cancelled")
    assert cancelled_again.data["data"]["cancelled_at"] == cancelled.data["data"]["cancelled_at"]


@pytest.mark.django_db
def test_bench_reads_separate_state_and_availability_source(client, coordinator, room, station, bench):
    _schedule(client, "room", room.pk)

    payload = client.get(f"/api/labs/benches/{bench.pk}").data["data"]

    assert payload["lifecycle_status"]["value"] == "in_service"
    assert payload["condition"]["value"] == "operational"
    assert payload["availability"] == {
        "value": "unavailable",
        "blocked_by": {"type": "room", "id": room.pk, "name": "R101"},
        "condition": "in_maintenance",
        "reason": "maintenance",
    }
    assert payload["activity_status"]["value"] == "idle"
    # The deprecated bench status keeps the old four values; only the bench's own downtime changes it.
    assert payload["status"]["value"] == "in_service"


@pytest.mark.django_db
def test_activity_rolls_up_from_bench_to_station_and_room(client, coordinator, room, station, bench):
    booking = _book(bench, coordinator, timezone.now(), timezone.now() + timedelta(hours=1))
    BenchBooking.objects.filter(pk=booking.pk).update(status=BookingStatus.IN_PROGRESS)

    bench_data = client.get(f"/api/labs/benches/{bench.pk}").data["data"]
    station_data = client.get(f"/api/labs/stations/{station.pk}").data["data"]
    room_data = client.get(f"/api/labs/rooms/{room.pk}").data["data"]

    assert bench_data["activity_status"]["value"] == "active"
    assert station_data["activity_status"]["value"] == "active"
    assert room_data["activity_status"]["value"] == "active"
    assert room_data["status"]["value"] == "reserved"  # deprecated value, computed from activity


@pytest.mark.django_db
def test_legacy_change_status_maps_onto_downtime_and_back(client, room):
    path = f"/api/labs/rooms/{room.pk}"

    maintenance = client.post(f"{path}/actions/change-status", {"status": "maintenance"}, format="json")
    assert maintenance.status_code == 200, maintenance.data
    assert maintenance.data["data"]["status"]["value"] == "maintenance"
    assert maintenance.data["data"]["condition"]["value"] == "in_maintenance"
    assert maintenance.data["data"]["lifecycle_status"]["value"] == "in_service"

    restricted = client.post(f"{path}/actions/change-status", {"status": "restricted"}, format="json")
    assert restricted.data["data"]["access_policy"]["value"] == "restricted"
    assert restricted.data["data"]["condition"]["value"] == "in_maintenance"

    available = client.post(f"{path}/actions/change-status", {"status": "available"}, format="json")
    assert available.data["data"]["status"]["value"] == "available"
    assert available.data["data"]["condition"]["value"] == "operational"
    assert available.data["data"]["access_policy"]["value"] == "open"

    reserved = client.post(f"{path}/actions/change-status", {"status": "reserved"}, format="json")
    assert reserved.status_code in (400, 422)


@pytest.mark.django_db
def test_retiring_a_room_needs_its_stations_retired_first(client, room, station):
    path = f"/api/labs/rooms/{room.pk}/actions/change-lifecycle"

    refused = client.post(path, {"lifecycle_status": "retired"}, format="json")
    retired_station = client.post(
        f"/api/labs/stations/{station.pk}/actions/change-lifecycle", {"lifecycle_status": "retired"}, format="json"
    )
    retired_room = client.post(path, {"lifecycle_status": "retired"}, format="json")
    back = client.post(path, {"lifecycle_status": "in_service"}, format="json")

    assert refused.status_code == 409, refused.data
    assert retired_station.status_code == 200, retired_station.data
    assert retired_room.status_code == 200, retired_room.data
    assert retired_room.data["data"]["status"]["value"] == "retired"
    assert back.status_code in (400, 422)  # retired is terminal


@pytest.mark.django_db
def test_retiring_ends_current_downtime_and_cancels_planned_windows(client, bench):
    current = _schedule(client, "bench", bench.pk, ends_at=timezone.now() + timedelta(hours=1)).data["data"]
    later = _schedule(client, "bench", bench.pk, *_window(hours_from_now=48)).data["data"]

    response = client.post(
        f"/api/labs/benches/{bench.pk}/actions/change-lifecycle", {"lifecycle_status": "retired"}, format="json"
    )

    assert response.status_code == 200, response.data
    assert current and later, (current, later)
    assert client.get(f"{URL}/{current['id']}").data["data"]["state"] == "ended"
    assert client.get(f"{URL}/{later['id']}").data["data"]["state"] == "cancelled"


@pytest.mark.django_db
def test_legacy_start_now_refuses_to_overlap_planned_downtime(room):
    starts_at, ends_at = _window(hours_from_now=24)
    ResourceDowntime.for_new_resource(room, condition="in_maintenance", starts_at=starts_at, ends_at=ends_at).save()

    with pytest.raises(ValidationError):
        ResourceDowntime.objects.start_now(room, condition="out_of_service", reason="fault")


@pytest.mark.django_db
def test_plain_lab_user_cannot_read_or_write_downtime(db, bench):
    user = grant_labs_role(User.objects.create_user(username="downtime-user"), "user")
    client = APIClient()
    client.force_authenticate(user)

    assert client.get(URL).status_code == 403
    assert _schedule(client, "bench", bench.pk).status_code == 403


@pytest.mark.django_db
def test_list_filters_and_query_budget_does_not_grow(client, room, station, bench):
    def count_queries():
        with CaptureQueriesContext(connection) as context:
            response = client.get(URL, {"resource_type": "bench", "resource_id": bench.pk, "state": "current"})
        assert response.status_code == 200, response.data
        return len(context.captured_queries), response.data["data"]

    _schedule(client, "bench", bench.pk)
    count_queries()  # warm the per-user role cache
    single, rows = count_queries()
    for index in range(3):
        other = Bench.objects.create(sku=f"B-{index}", setup_location=station)
        _schedule(client, "bench", other.pk)
    repeated, _ = count_queries()

    assert len(rows) == 1
    assert repeated == single


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/api/labs/benches", "/api/labs/stations", "/api/labs/rooms"])
def test_resource_lists_compute_state_in_a_constant_number_of_queries(client, coordinator, path):
    def count_queries():
        with CaptureQueriesContext(connection) as context:
            response = client.get(path)
        assert response.status_code == 200, response.data
        return len(context.captured_queries)

    def add_tree(index):
        room = Room.objects.create(sku=f"R-{index}")
        station = Station.objects.create(sku=f"S-{index}", room=room)
        bench = Bench.objects.create(sku=f"B-{index}", setup_location=station)
        _book(bench, coordinator, timezone.now() + timedelta(hours=2), timezone.now() + timedelta(hours=3))
        ResourceDowntime.for_new_resource(room, condition="in_maintenance", starts_at=timezone.now()).save()

    add_tree(0)
    count_queries()  # warm the per-user role cache
    single = count_queries()
    for index in range(1, 4):
        add_tree(index)

    assert count_queries() == single
