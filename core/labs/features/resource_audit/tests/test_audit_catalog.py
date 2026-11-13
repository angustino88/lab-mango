"""Audit catalog: cursor-paged offline list of every auditable resource."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.locations.public import record_room_status, record_station_status
from core.labs.models import Bench, Equipment, EquipmentCategory, EquipmentKind, License, Room, RoomSlot, Station
from core.labs.models.resource.license.license import (
    LicenseCategory,
    LicenseProduct,
    LicenseStatusRecord,
    LicenseType,
    LicenseVendor,
)
from tests.factories import UserFactory, grant_labs_role

URL = "/api/labs/audit-catalog"


@pytest.fixture()
def client(db):
    api_client = APIClient()
    api_client.force_authenticate(user=grant_labs_role(UserFactory(), "coord"))
    return api_client


@pytest.fixture()
def resources(db):
    room = Room.objects.create(sku="CAT-R-1", name="Catalog room", layout_rows=2, layout_columns=3)
    slot = RoomSlot.objects.create(room=room, row_index=1, col_index=2, slot_code="R1C2")
    station = Station.objects.create(sku="CAT-S-1", name="Catalog station", room=room, slot=slot)
    bench = Bench.objects.create(sku="CAT-B-1", name="Catalog bench", setup_location=station)
    kind = EquipmentKind.objects.create(
        category=EquipmentCategory.objects.create(name="Catalog category", definition="Catalog fixture"),
        name="Catalog kind",
    )
    equipment = Equipment.objects.create(sku="CAT-E-1", name="Catalog scope", kind=kind, serial_number="SN-001")
    license_item = License.objects.create(
        sku="CAT-L-1",
        name="Catalog license",
        product=LicenseProduct.objects.create(name="Catalog product"),
        vendor=LicenseVendor.objects.create(name="Catalog vendor"),
        type=LicenseType.objects.create(name="Catalog type"),
        category=LicenseCategory.objects.create(name="Catalog license category"),
        identifier="SECRET-LICENSE-KEY",
    )
    return {"room": room, "station": station, "bench": bench, "equipment": equipment, "license": license_item}


def _all_pages(client, first_query):
    response = client.get(URL, first_query)
    assert response.status_code == 200, response.content
    pages = [response.json()]
    while pages[-1]["meta"]["pagination"]["next_cursor"]:
        response = client.get(URL, {"cursor": pages[-1]["meta"]["pagination"]["next_cursor"]})
        assert response.status_code == 200, response.content
        pages.append(response.json())
    return pages


@pytest.mark.django_db
class TestAuditCatalog:
    def test_full_download_returns_every_type_with_projection(self, client, resources):
        body = client.get(URL).json()

        by_type = {item["resource_type"]: item for item in body["data"]}
        assert set(by_type) == {"equipment", "bench", "station", "room", "license"}
        equipment = by_type["equipment"]
        assert equipment["uid"] == str(resources["equipment"].uid)
        assert equipment["sku"] == "CAT-E-1"
        assert equipment["serial_number"] == "SN-001"
        assert equipment["status"] == resources["equipment"].lifecycle_state
        assert equipment["condition"] == resources["equipment"].condition
        assert equipment["deleted"] is False
        assert by_type["bench"]["location"] == "Catalog station"
        assert by_type["station"]["location"] == "Catalog room"
        assert body["meta"]["pagination"] == {
            "count": None,
            "page_size": 500,
            "next_cursor": None,
            "previous_cursor": None,
        }
        assert body["meta"]["server_time"]

    def test_license_key_is_never_returned(self, client, resources):
        response = client.get(URL)

        assert b"SECRET-LICENSE-KEY" not in response.content
        assert all("identifier" not in item for item in response.json()["data"])

    def test_cursor_pages_cover_every_row_once_across_types(self, client, resources):
        pages = _all_pages(client, {"page_size": 2})

        uids = [item["uid"] for page in pages for item in page["data"]]
        assert len(uids) == 5 == len(set(uids))
        assert all(len(page["data"]) <= 2 for page in pages)
        assert len({page["meta"]["server_time"] for page in pages}) == 1

    def test_changed_since_returns_changes_and_deletions_only(self, client, resources):
        since = timezone.now()
        Bench.objects.filter(pk=resources["bench"].pk).update(
            name="Renamed bench", modified=since + timedelta(seconds=1)
        )
        Room.all_objects.filter(pk=resources["room"].pk).update(deleted_at=since + timedelta(seconds=1))

        body = client.get(URL, {"changed_since": since.isoformat()}).json()

        by_uid = {item["uid"]: item for item in body["data"]}
        assert set(by_uid) == {str(resources["bench"].uid), str(resources["room"].uid)}
        assert by_uid[str(resources["bench"].uid)]["name"] == "Renamed bench"
        assert by_uid[str(resources["room"].uid)]["deleted"] is True

    def test_full_download_excludes_deleted_rows(self, client, resources):
        Room.all_objects.filter(pk=resources["room"].pk).update(deleted_at=timezone.now())

        types = {item["resource_type"] for item in client.get(URL).json()["data"]}

        assert "room" not in types

    @pytest.mark.parametrize(
        "query",
        [
            {"cursor": "not-a-real-cursor"},
            {"page_size": 0},
            {"page_size": 1001},
            {"page": 2},
            {"unknown": "x"},
            {"changed_since": "yesterday"},
        ],
    )
    def test_invalid_queries_return_400(self, client, resources, query):
        response = client.get(URL, query)

        assert response.status_code == 400

    def test_tampered_cursor_returns_invalid_cursor(self, client, resources):
        response = client.get(URL, {"cursor": "abc:def"})

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_cursor"

    def test_cursor_cannot_be_combined_with_filters(self, client, resources):
        cursor = client.get(URL, {"page_size": 1}).json()["meta"]["pagination"]["next_cursor"]

        response = client.get(URL, {"cursor": cursor, "page_size": 5})

        assert response.status_code == 400

    def test_query_budget_is_one_query_per_type(self, client, resources, django_assert_max_num_queries):
        # Authentication and role checks add a few queries; the catalog itself is at most five.
        with django_assert_max_num_queries(10):
            assert client.get(URL).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("role", [None, "user"])
def test_users_without_coordinator_role_are_denied(role):
    user = UserFactory()
    if role:
        grant_labs_role(user, role)
    api_client = APIClient()
    api_client.force_authenticate(user=user)

    assert api_client.get(URL).status_code == 403


@pytest.mark.django_db
def test_anonymous_is_denied():
    assert APIClient().get(URL).status_code in (401, 403)


def _by_uid(body):
    return {item["uid"]: item for item in body["data"]}


@pytest.mark.django_db
class TestCatalogStatusAndDelta:
    def test_latest_status_record_is_the_status(self, client, resources):
        # Room and station status is a stored column, changed only through the locations command.
        record_station_status(station_id=resources["station"].pk, actor=None, status="available")
        record_station_status(station_id=resources["station"].pk, actor=None, status="maintenance")
        record_room_status(room_id=resources["room"].pk, actor=None, status="closed")
        LicenseStatusRecord.objects.create(license=resources["license"], status="expired")

        items = _by_uid(client.get(URL).json())

        assert items[str(resources["station"].uid)]["status"] == "maintenance"
        assert items[str(resources["room"].uid)]["status"] == "closed"
        assert items[str(resources["license"].uid)]["status"] == "expired"

    def test_license_expiry_is_returned(self, client, resources):
        expiry = timezone.now() + timedelta(days=30)
        License.objects.filter(pk=resources["license"].pk).update(expiry_date=expiry)

        items = _by_uid(client.get(URL).json())

        assert items[str(resources["license"].uid)]["expiry_date"] is not None
        assert items[str(resources["equipment"].uid)]["expiry_date"] is None

    def test_renamed_station_returns_its_benches(self, client, resources):
        since = timezone.now()
        Station.objects.filter(pk=resources["station"].pk).update(
            name="Renamed station", modified=since + timedelta(seconds=1)
        )

        items = _by_uid(client.get(URL, {"changed_since": since.isoformat()}).json())

        assert items[str(resources["bench"].uid)]["location"] == "Renamed station"
        assert str(resources["station"].uid) in items

    def test_renamed_room_returns_its_stations(self, client, resources):
        since = timezone.now()
        Room.objects.filter(pk=resources["room"].pk).update(name="Renamed room", modified=since + timedelta(seconds=1))

        items = _by_uid(client.get(URL, {"changed_since": since.isoformat()}).json())

        assert items[str(resources["station"].uid)]["location"] == "Renamed room"

    def test_new_status_record_returns_the_resource(self, client, resources):
        since = timezone.now()
        record_station_status(station_id=resources["station"].pk, actor=None, status="issue")
        LicenseStatusRecord.objects.create(license=resources["license"], status="revoked")

        items = _by_uid(client.get(URL, {"changed_since": since.isoformat()}).json())

        # The status command updates the station row, so its bench (whose location parent changed) comes too.
        assert set(items) == {
            str(resources["station"].uid),
            str(resources["bench"].uid),
            str(resources["license"].uid),
        }
        assert items[str(resources["station"].uid)]["status"] == "issue"

    def test_unchanged_resources_are_not_returned(self, client, resources):
        since = timezone.now() + timedelta(seconds=1)

        assert client.get(URL, {"changed_since": since.isoformat()}).json()["data"] == []

    def test_delta_query_budget(self, client, resources, django_assert_max_num_queries):
        since = (timezone.now() - timedelta(days=1)).isoformat()

        with django_assert_max_num_queries(10):
            assert client.get(URL, {"changed_since": since}).status_code == 200
