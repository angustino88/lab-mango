"""Downtime windows that stay open to lab staff bookings (``booking_access``).

Design: docs/proposals/downtime-lab-staff-booking-access.md (rules BA1-BA7).
"""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.bench_bookings.exceptions import BenchBookingConflict
from core.labs.features.bench_bookings.public import (
    CreateBenchBookingInput,
    UpdateBenchBookingInput,
    create_bench_booking,
    update_bench_booking,
)
from core.labs.features.downtime.public import (
    ChangeDowntimeBookingAccessInput,
    DowntimeBookingConflict,
    change_downtime_booking_access,
)
from core.labs.models import (
    Bench,
    BenchBooking,
    BookingStatus,
    DowntimeBookingAccess,
    EquipmentAssignment,
    ResourceDowntime,
    Room,
    Station,
    StationType,
)
from core.users.models import User
from tests.factories import create_computing_equipment, grant_labs_role

URL = "/api/labs/downtimes"


def _user(username: str, role: str) -> User:
    return grant_labs_role(User.objects.create_user(username=username, display_name=username), role)


@pytest.fixture
def coordinator(db):
    return _user("access-coord", "coord")


@pytest.fixture
def admin(db):
    return _user("access-admin", "admin")


@pytest.fixture
def member(db):
    return _user("access-member", "user")


@pytest.fixture
def client(coordinator):
    result = APIClient()
    result.force_authenticate(coordinator)
    return result


@pytest.fixture
def room(db):
    return Room.objects.create(name="R201", sku="R201")


@pytest.fixture
def station(room):
    return Station.objects.create(name="ST-11", sku="ST-11", room=room, type=StationType.objects.create(name="Desk"))


def _with_computer(bench):
    EquipmentAssignment.objects.create(
        bench=bench,
        equipment=create_computing_equipment(sku=f"PC-{bench.sku}", name=f"PC {bench.sku}"),
        assigned_at=timezone.now() - timedelta(hours=1),
    )
    return bench


@pytest.fixture
def bench(station):
    return _with_computer(Bench.objects.create(name="B-Access-01", sku="B-ACCESS-01", setup_location=station))


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


def _change_access(client, downtime_id, booking_access, **extra):
    return client.post(
        f"{URL}/{downtime_id}/actions/change-booking-access",
        {"booking_access": booking_access, **extra},
        format="json",
    )


# BA1: closed is the default and keeps the previous behavior (nobody books, staff included).
@pytest.mark.django_db
def test_windows_are_closed_to_everyone_by_default(client, coordinator, admin, bench):
    starts_at, ends_at = _window()

    created = _schedule(client, "bench", bench.pk, starts_at, ends_at)

    assert created.status_code == 201, created.data
    assert created.data["data"]["booking_access"] == {"value": "closed", "label": "Closed to all bookings"}
    for actor in (coordinator, admin):
        with pytest.raises(BenchBookingConflict, match="Bench is in maintenance"):
            _book(bench, actor, starts_at, ends_at)


# BA2: a lab_staff window lets coordinators and administrators book, and nobody else.
@pytest.mark.django_db
@pytest.mark.parametrize("resource_type", ["room", "station", "bench"])
def test_lab_staff_window_admits_coordinators_and_admins_only(
    client, coordinator, admin, member, room, station, bench, resource_type
):
    resource_id = {"room": room.pk, "station": station.pk, "bench": bench.pk}[resource_type]
    starts_at, ends_at = _window(hours=4)

    created = _schedule(client, resource_type, resource_id, starts_at, ends_at, booking_access="lab_staff")

    assert created.status_code == 201, created.data
    assert created.data["data"]["booking_access"] == {"value": "lab_staff", "label": "Lab staff only"}
    with pytest.raises(BenchBookingConflict, match="Only lab coordinators and administrators can book it"):
        _book(bench, member, starts_at, starts_at + timedelta(hours=1))
    assert _book(bench, coordinator, starts_at, starts_at + timedelta(hours=1)).creator == coordinator
    assert _book(bench, admin, starts_at + timedelta(hours=1), starts_at + timedelta(hours=2)).creator == admin


@pytest.mark.django_db
def test_a_closed_window_at_another_level_still_blocks_lab_staff(client, coordinator, room, bench):
    starts_at, ends_at = _window()
    _schedule(client, "room", room.pk, starts_at, ends_at, booking_access="lab_staff")
    _schedule(client, "bench", bench.pk, starts_at, ends_at)

    with pytest.raises(BenchBookingConflict, match="Bench is in maintenance"):
        _book(bench, coordinator, starts_at, ends_at)


# BA3: scheduling a lab_staff window keeps staff bookings and still reports everyone else's.
@pytest.mark.django_db
def test_scheduling_a_lab_staff_window_only_conflicts_with_non_staff_bookings(
    client, coordinator, member, room, bench
):
    starts_at, ends_at = _window(hours=4)
    staff_booking = _book(bench, coordinator, starts_at, starts_at + timedelta(hours=1))
    member_booking = _book(bench, member, starts_at + timedelta(hours=2), starts_at + timedelta(hours=3))

    refused = _schedule(client, "room", room.pk, starts_at, ends_at, booking_access="lab_staff")

    assert refused.status_code == 409, refused.data
    assert [d["field"] for d in refused.data["error"]["details"]] == [f"bench_bookings.{member_booking.pk}"]

    confirmed = _schedule(
        client, "room", room.pk, starts_at, ends_at, booking_access="lab_staff", cancel_conflicting_bookings=True
    )

    assert confirmed.status_code == 201, confirmed.data
    staff_booking.refresh_from_db()
    member_booking.refresh_from_db()
    assert staff_booking.status == BookingStatus.RESERVED
    assert member_booking.status == BookingStatus.CANCELLED


# BA4: the holder decides, not the editor.
@pytest.mark.django_db
def test_a_coordinator_cannot_move_a_members_booking_into_a_lab_staff_window(client, coordinator, member, bench):
    starts_at, ends_at = _window(hours=2)
    _schedule(client, "bench", bench.pk, starts_at, ends_at, booking_access="lab_staff")
    booking = _book(bench, member, ends_at + timedelta(hours=1), ends_at + timedelta(hours=2))

    with pytest.raises(BenchBookingConflict, match="Only lab coordinators and administrators"):
        update_bench_booking(
            actor=coordinator,
            data=UpdateBenchBookingInput(booking.pk, {"starts_at": starts_at, "ends_at": ends_at}),
        )


# BA5: changing the access of an existing window.
@pytest.mark.django_db
def test_opening_then_closing_a_window_follows_rs4(client, coordinator, bench):
    starts_at, ends_at = _window(hours=3)
    window = _schedule(client, "bench", bench.pk, starts_at, ends_at).data["data"]

    opened = _change_access(client, window["id"], "lab_staff")
    opened_again = _change_access(client, window["id"], "lab_staff")

    assert opened.status_code == 200, opened.data
    assert opened.data["data"]["booking_access"]["value"] == "lab_staff"
    assert opened_again.data["data"]["updated_at"] == opened.data["data"]["updated_at"]
    staff_booking = _book(bench, coordinator, starts_at, starts_at + timedelta(hours=1))

    refused = _change_access(client, window["id"], "closed")

    assert refused.status_code == 409, refused.data
    assert refused.data["error"]["code"] == "downtime_booking_conflict"
    assert [d["field"] for d in refused.data["error"]["details"]] == [f"bench_bookings.{staff_booking.pk}"]
    assert ResourceDowntime.objects.get(pk=window["id"]).booking_access == DowntimeBookingAccess.LAB_STAFF

    closed = _change_access(client, window["id"], "closed", cancel_conflicting_bookings=True)

    assert closed.status_code == 200, closed.data
    assert closed.data["data"]["booking_access"]["value"] == "closed"
    staff_booking.refresh_from_db()
    assert staff_booking.status == BookingStatus.CANCELLED
    with pytest.raises(BenchBookingConflict):
        _book(bench, coordinator, starts_at, starts_at + timedelta(hours=1))


@pytest.mark.django_db
def test_ended_and_cancelled_windows_keep_their_access(client, bench):
    current = _schedule(client, "bench", bench.pk).data["data"]
    client.post(f"{URL}/{current['id']}/actions/end")
    later = _schedule(client, "bench", bench.pk, *_window(hours_from_now=24)).data["data"]
    client.post(f"{URL}/{later['id']}/actions/cancel")

    for window_id in (current["id"], later["id"]):
        response = _change_access(client, window_id, "lab_staff")
        assert response.status_code == 409, response.data
        assert response.data["error"]["code"] == "downtime_not_allowed"


@pytest.mark.django_db
def test_change_booking_access_of_a_missing_window_is_not_found(client):
    assert _change_access(client, 999999, "lab_staff").status_code == 404


# BA6: equipment reservations are not bench bookings; lab staff access is refused for them.
@pytest.mark.django_db
def test_lab_staff_access_is_refused_for_equipment(client):
    unit = create_computing_equipment(sku="PC-ACCESS", name="PC access")

    created = _schedule(client, "equipment", unit.pk, booking_access="lab_staff")

    assert created.status_code == 422, created.data
    assert created.data["error"]["details"][0]["field"].startswith("booking_access")
    assert not ResourceDowntime.objects.exists()


@pytest.mark.django_db
def test_change_booking_access_is_refused_for_equipment_windows(coordinator):
    unit = create_computing_equipment(sku="PC-ACCESS-2", name="PC access 2")
    window = ResourceDowntime.for_new_resource(unit, condition="in_maintenance", starts_at=timezone.now())
    window.save()

    with pytest.raises(ValidationError, match="not equipment"):
        change_downtime_booking_access(
            ChangeDowntimeBookingAccessInput(window.pk, DowntimeBookingAccess.LAB_STAFF), actor=coordinator
        )


# BA7: authorization and database guards.
@pytest.mark.django_db
def test_plain_lab_user_cannot_change_booking_access(client, member, bench):
    window = _schedule(client, "bench", bench.pk).data["data"]
    member_client = APIClient()
    member_client.force_authenticate(member)

    assert _change_access(member_client, window["id"], "lab_staff").status_code == 403
    assert ResourceDowntime.objects.get(pk=window["id"]).booking_access == DowntimeBookingAccess.CLOSED


@pytest.mark.django_db
def test_database_refuses_an_unknown_booking_access(bench):
    window = ResourceDowntime.for_new_resource(bench, condition="in_maintenance", starts_at=timezone.now())
    window.booking_access = "everyone"

    with pytest.raises(IntegrityError), transaction.atomic():
        window.save()


@pytest.mark.django_db
def test_closing_while_a_staff_booking_is_in_progress_is_refused(client, coordinator, bench):
    window = _schedule(client, "bench", bench.pk, booking_access="lab_staff").data["data"]
    booking = _book(bench, coordinator, timezone.now(), timezone.now() + timedelta(hours=1))
    BenchBooking.objects.filter(pk=booking.pk).update(status=BookingStatus.IN_PROGRESS)

    with pytest.raises(DowntimeBookingConflict):
        change_downtime_booking_access(
            ChangeDowntimeBookingAccessInput(window["id"], DowntimeBookingAccess.CLOSED), actor=coordinator
        )


# Reads: availability tells the frontend that staff may still book.
@pytest.mark.django_db
def test_availability_reports_who_may_still_book(client, room, bench):
    window = _schedule(client, "room", room.pk, booking_access="lab_staff").data["data"]

    bench_read = client.get(f"/api/labs/benches/{bench.pk}").data["data"]["availability"]
    room_read = client.get(f"/api/labs/rooms/{room.pk}").data["data"]["availability"]

    assert bench_read["status"]["value"] == "unavailable"
    assert bench_read["booking_access"] == {"value": "lab_staff", "label": "Lab staff only"}
    assert room_read["booking_access"]["value"] == "lab_staff"

    _change_access(client, window["id"], "closed")

    assert client.get(f"/api/labs/benches/{bench.pk}").data["data"]["availability"]["booking_access"]["value"] == (
        "closed"
    )


@pytest.mark.django_db
def test_list_filters_by_booking_access(client, room, bench):
    _schedule(client, "room", room.pk, booking_access="lab_staff")
    _schedule(client, "bench", bench.pk)

    response = client.get(URL, {"booking_access": "lab_staff"})

    assert response.status_code == 200, response.data
    assert [row["resource"]["type"] for row in response.data["data"]] == ["room"]


# Moves keep the same rule: a lab_staff parent window does not block staff bookings.
@pytest.mark.django_db
def test_moving_a_bench_under_a_lab_staff_window_only_counts_non_staff_bookings(client, coordinator, member, bench):
    starts_at, ends_at = _window(hours_from_now=3)
    staff_booking = _book(bench, coordinator, starts_at, starts_at + timedelta(hours=1))
    target = Station.objects.create(sku="ST-STAFF", room=bench.setup_location.room)
    ResourceDowntime.for_new_resource(
        target, condition="in_maintenance", starts_at=timezone.now(), booking_access=DowntimeBookingAccess.LAB_STAFF
    ).save()
    member_booking = _book(bench, member, starts_at + timedelta(hours=1), ends_at)

    refused = client.post(
        f"/api/labs/benches/{bench.pk}/actions/place", {"setup_location_id": target.pk}, format="json"
    )

    assert refused.status_code == 409, refused.data
    assert [d["field"] for d in refused.data["error"]["details"]] == [f"bench_bookings.{member_booking.pk}"]
    BenchBooking.objects.filter(pk=member_booking.pk).update(status=BookingStatus.CANCELLED, cancellation_reason="x")

    moved = client.post(f"/api/labs/benches/{bench.pk}/actions/place", {"setup_location_id": target.pk}, format="json")

    assert moved.status_code == 200, moved.data
    staff_booking.refresh_from_db()
    assert staff_booking.status == BookingStatus.RESERVED
