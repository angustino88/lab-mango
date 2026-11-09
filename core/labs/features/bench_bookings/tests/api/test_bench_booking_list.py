"""Creator and coordinator visibility for the paginated bench booking collection."""

import re
from datetime import datetime, timedelta
from datetime import timezone as datetime_timezone

import pytest
from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.users.models import URSGroup
from core.users.public import clear_labs_roles_cache
from core.users.tests.factories import UserFactory

URL = "/api/labs/bench-bookings"


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _role(user, role, role_id):
    group = Group.objects.create(name=f"booking-list-{role}-{role_id}")
    URSGroup.objects.create(group=group, urs_group_id=role_id, labs_role=role)
    user.groups.add(group)


@pytest.mark.django_db
class TestBenchBookingList:
    def test_user_sees_only_created_bookings_and_creator_is_used(self, actor, bench, make_booking, future_window):
        _role(actor, "user", 80101)
        starts_at, ends_at = future_window
        own = make_booking(starts_at=starts_at, ends_at=ends_at)
        other = UserFactory(username="booking-list-other")
        elsewhere = make_booking(starts_at=starts_at + timedelta(hours=2), ends_at=ends_at + timedelta(hours=2))
        elsewhere.creator = other
        elsewhere.requester = actor
        elsewhere.save(update_fields=["creator", "requester"])
        own.requester = other
        own.save(update_fields=["requester"])

        for query in (
            {},
            {"view_side": "my_booking", "page": 1, "page_size": 10},
            {"view_side": "my_booking", "page": 1, "page_size": 10, "creator": actor.username},
        ):
            response = _client(actor).get(URL, query)
            assert response.status_code == 200
            assert [item["id"] for item in response.json()["data"]] == [own.pk]
            assert response.json()["meta"]["pagination"]["count"] == 1

    @pytest.mark.parametrize("role,role_id", [("coord", 80102), ("admin", 80103)])
    def test_coordinator_and_admin_see_all_but_can_select_my_booking(
        self, actor, make_booking, future_window, role, role_id
    ):
        _role(actor, role, role_id)
        starts_at, ends_at = future_window
        own = make_booking(starts_at=starts_at, ends_at=ends_at)
        other = UserFactory(username=f"booking-list-{role}-other")
        another = make_booking(starts_at=starts_at + timedelta(hours=2), ends_at=ends_at + timedelta(hours=2))
        another.creator = other
        another.save(update_fields=["creator"])

        response = _client(actor).get(URL, {"page": 1, "page_size": 1})
        assert response.status_code == 200
        assert response.json()["meta"]["pagination"]["count"] == 2
        assert [item["id"] for item in response.json()["data"]] == [another.pk]

        mine = _client(actor).get(URL, {"view_side": "my_booking"})
        assert mine.status_code == 200
        assert [item["id"] for item in mine.json()["data"]] == [own.pk]

    def test_anonymous_and_api_key_without_user_cannot_see_bookings(
        self, actor, make_booking, future_window, monkeypatch
    ):
        starts_at, ends_at = future_window
        make_booking(starts_at=starts_at, ends_at=ends_at)
        assert APIClient().get(URL).status_code in (401, 403)
        monkeypatch.setattr("rest_framework_api_key.permissions.HasAPIKey.has_permission", lambda *args: True)
        response = APIClient().get(URL)
        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_temporal_overlap_respects_member_coordinator_and_api_key_scope(
        self, actor, make_booking, other_bench, monkeypatch
    ):
        lower = datetime(2026, 11, 2, tzinfo=datetime_timezone.utc)
        upper = lower + timedelta(days=1)
        spanning = make_booking(starts_at=lower - timedelta(days=1), ends_at=upper + timedelta(days=1))
        other = UserFactory(username="booking-temporal-other")
        hidden = make_booking(
            starts_at=lower + timedelta(hours=1), ends_at=lower + timedelta(hours=2), bench_obj=other_bench
        )
        hidden.creator = other
        hidden.save(update_fields=["creator"])
        query = {"starts_at_after": lower.isoformat(), "starts_at_before": upper.isoformat()}

        _role(actor, "user", 80109)
        member = _client(actor).get(URL, query)
        assert member.status_code == 200
        assert {item["id"] for item in member.json()["data"]} == {spanning.pk}
        assert member.json()["meta"]["pagination"]["count"] == 1

        _role(actor, "coord", 80110)
        clear_labs_roles_cache(actor)
        coordinator = _client(actor).get(URL, query)
        assert coordinator.status_code == 200
        assert {item["id"] for item in coordinator.json()["data"]} == {spanning.pk, hidden.pk}
        assert coordinator.json()["meta"]["pagination"]["count"] == 2

        monkeypatch.setattr("rest_framework_api_key.permissions.HasAPIKey.has_permission", lambda *args: True)
        api_key = APIClient().get(URL, query)
        assert api_key.status_code == 200
        assert api_key.json()["data"] == []
        assert api_key.json()["meta"]["pagination"]["count"] == 0

    @pytest.mark.parametrize("query", [{"view_side": "invalid"}, {"bogus": "1"}, {"page_size": 101}])
    def test_invalid_parameters_return_standard_error(self, api_client, query):
        response = api_client.get(URL, query)
        assert response.status_code == 400
        assert response.json()["error"]["code"] in {"invalid_query", "validation_failed"}

    @pytest.mark.parametrize(
        "ordering,expected",
        [
            ("ends_at", [1, 2, 0]),
            ("-ends_at", [0, 2, 1]),
        ],
    )
    def test_ordering_by_ends_at_is_supported_in_both_directions(
        self, actor, make_booking, future_window, ordering, expected
    ):
        _role(actor, "coord", 80111)
        starts_at, _ = future_window
        bookings = [
            make_booking(starts_at=starts_at + timedelta(hours=index), ends_at=starts_at + timedelta(hours=end_hour))
            for index, end_hour in enumerate((4, 2, 2))
        ]

        response = _client(actor).get(URL, {"ordering": ordering, "page_size": 10})

        assert response.status_code == 200
        assert [item["id"] for item in response.json()["data"]] == [bookings[index].pk for index in expected]

    def test_ordering_has_stable_id_tiebreaker_across_pages(self, actor, make_booking, future_window):
        _role(actor, "coord", 80112)
        starts_at, _ = future_window
        first = make_booking(starts_at=starts_at, ends_at=starts_at + timedelta(hours=3))
        second = make_booking(starts_at=starts_at + timedelta(hours=1), ends_at=first.ends_at)

        page_one = _client(actor).get(URL, {"ordering": "ends_at", "page": 1, "page_size": 1})
        page_two = _client(actor).get(URL, {"ordering": "ends_at", "page": 2, "page_size": 1})

        assert page_one.status_code == page_two.status_code == 200
        assert page_one.json()["data"][0]["id"] == min(first.pk, second.pk)
        assert page_two.json()["data"][0]["id"] == max(first.pk, second.pk)

    def test_omitted_ordering_preserves_existing_default(self, actor, make_booking, future_window):
        _role(actor, "coord", 80113)
        starts_at, ends_at = future_window
        earlier = make_booking(starts_at=starts_at, ends_at=ends_at)
        later = make_booking(starts_at=starts_at + timedelta(hours=1), ends_at=ends_at + timedelta(hours=1))

        response = _client(actor).get(URL)

        assert response.status_code == 200
        assert [item["id"] for item in response.json()["data"]] == [later.pk, earlier.pk]

    @pytest.mark.parametrize(
        "ordering,expected",
        [
            ("starts_at", [0, 1, 2]),
            ("created_at", [0, 1, 2]),
            ("id", [0, 1, 2]),
            ("-id", [2, 1, 0]),
            ("-ends_at,starts_at", [0, 1, 2]),
        ],
    )
    def test_other_allowlisted_orderings_and_mixed_fields(
        self, actor, make_booking, future_window, ordering, expected
    ):
        _role(actor, "coord", 80115)
        starts_at, _ = future_window
        bookings = [
            make_booking(starts_at=starts_at + timedelta(hours=index), ends_at=starts_at + timedelta(hours=2))
            for index in range(3)
        ]

        response = _client(actor).get(URL, {"ordering": ordering, "page_size": 10})

        assert response.status_code == 200
        assert [item["id"] for item in response.json()["data"]] == [bookings[index].pk for index in expected]

    @pytest.mark.parametrize(
        "ordering",
        [
            "",
            "unknown",
            "ends_at,",
            ",ends_at",
            "ends_at, ends_at",
            "ends_at,-ends_at",
            "ends_at,created_at,ends_at",
            "bench__name",
        ],
    )
    def test_invalid_ordering_is_rejected(self, api_client, ordering):
        response = api_client.get(URL, {"ordering": ordering})

        assert response.status_code == 400
        assert response.json()["error"]["details"][0]["field"] == "ordering"

    def test_repeated_ordering_parameter_is_rejected(self, api_client):
        response = api_client.get(f"{URL}?ordering=ends_at&ordering=-ends_at")

        assert response.status_code == 400
        assert response.json()["error"]["details"][0]["field"] == "ordering"

    @pytest.mark.parametrize("ordering", [["unknown"], ["bench__name"], ["-ends_at", "ends_at"]])
    def test_selector_rejects_unvalidated_ordering(self, actor, ordering):
        from core.labs.features.bench_bookings.queries import list_bench_bookings

        with pytest.raises(ValueError, match="Unsupported bench booking ordering"):
            list_bench_bookings(actor=actor, ordering=ordering)

    def test_query_count_does_not_grow_with_related_rows(
        self, actor, bench, project, make_booking, future_window, django_assert_num_queries
    ):
        _role(actor, "user", 80104)
        starts_at, ends_at = future_window
        for index in range(3):
            booking = make_booking(
                starts_at=starts_at + timedelta(hours=index * 2),
                ends_at=ends_at + timedelta(hours=index * 2),
            )
            booking.project = project
            booking.save(update_fields=["project"])

        client = _client(actor)
        # One role lookup, one count and one page query; bench/project are joined.
        with django_assert_num_queries(3):
            response = client.get(URL)
        assert response.status_code == 200
        assert len(response.json()["data"]) == 3

    def test_custom_ordering_keeps_query_count_bounded(
        self, actor, bench, project, make_booking, future_window, django_assert_num_queries
    ):
        _role(actor, "user", 80114)
        starts_at, ends_at = future_window
        for index in range(3):
            booking = make_booking(
                starts_at=starts_at + timedelta(hours=index * 2),
                ends_at=ends_at + timedelta(hours=index * 2),
            )
            booking.project = project
            booking.save(update_fields=["project"])

        with django_assert_num_queries(3):
            response = _client(actor).get(URL, {"ordering": "ends_at"})

        assert response.status_code == 200
        assert len(response.json()["data"]) == 3

    def test_date_range_filters_half_open_overlaps(self, actor, bench, make_booking):
        _role(actor, "coord", 80105)
        default_zone = timezone.get_default_timezone()
        lower = datetime(2026, 11, 2, 0, 0, tzinfo=default_zone)
        upper = datetime(2026, 11, 9, 0, 0, tzinfo=default_zone)
        before = make_booking(starts_at=lower - timedelta(days=2), ends_at=lower)
        starts_at_lower = make_booking(starts_at=lower, ends_at=lower + timedelta(hours=1))
        inside = make_booking(starts_at=lower + timedelta(days=1), ends_at=lower + timedelta(days=1, hours=1))
        ends_at_upper = make_booking(starts_at=upper - timedelta(hours=1), ends_at=upper)
        after = make_booking(starts_at=upper, ends_at=upper + timedelta(hours=1))

        response = _client(actor).get(
            URL,
            {"starts_at_after": "2026-11-02", "starts_at_before": "2026-11-09", "view_side": "booking_calendar"},
        )

        assert response.status_code == 200
        returned_ids = {item["id"] for item in response.json()["data"]}
        assert starts_at_lower.pk in returned_ids
        assert inside.pk in returned_ids
        assert ends_at_upper.pk in returned_ids
        assert before.pk not in returned_ids
        assert after.pk not in returned_ids

    def test_date_range_bounds_are_partial_and_datetime_offsets_are_instants(self, actor, make_booking):
        _role(actor, "coord", 80106)
        base = datetime(2026, 11, 2, 0, 0, tzinfo=datetime_timezone.utc)
        overlapping = make_booking(starts_at=base - timedelta(hours=1), ends_at=base + timedelta(hours=1))
        ends_at_lower = make_booking(starts_at=base - timedelta(hours=2), ends_at=base, status="cancelled")
        begins_at_upper = make_booking(starts_at=base, ends_at=base + timedelta(hours=1), status="cancelled")

        lower_response = _client(actor).get(URL, {"starts_at_after": "2026-11-02T07:00:00+07:00"})
        upper_response = _client(actor).get(URL, {"starts_at_before": "2026-11-02T01:00:00+01:00"})

        assert lower_response.status_code == 200
        assert overlapping.pk in {item["id"] for item in lower_response.json()["data"]}
        assert ends_at_lower.pk not in {item["id"] for item in lower_response.json()["data"]}
        assert upper_response.status_code == 200
        assert overlapping.pk in {item["id"] for item in upper_response.json()["data"]}
        assert begins_at_upper.pk not in {item["id"] for item in upper_response.json()["data"]}

    @override_settings(TIME_ZONE="Asia/Bangkok")
    def test_date_only_bound_uses_configured_timezone(self):
        from core.labs.features.bench_bookings.api.serializers import BenchBookingListQuerySerializer

        serializer = BenchBookingListQuerySerializer(data={"starts_at_after": "2026-11-02"})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["starts_at_after"].utcoffset() == timedelta(hours=7)

    @pytest.mark.parametrize(
        "query",
        [
            {"starts_at_after": ""},
            {"starts_at_before": "2026-02-30"},
            {"starts_at_after": "2026-11-02T12:00:00"},
            {"starts_at_before": "2026-11-02 12:00:00Z"},
            {"starts_at_after": "2026-11-02", "starts_at_before": "2026-11-02"},
            {"starts_at_after": "2026-11-03", "starts_at_before": "2026-11-02"},
        ],
    )
    def test_invalid_date_range_parameters_return_standard_error(self, api_client, query):
        response = api_client.get(URL, query)
        assert response.status_code == 400
        assert response.json()["error"]["code"] in {"invalid_query", "validation_failed"}

    def test_repeated_range_parameter_is_rejected(self, api_client):
        response = api_client.get(f"{URL}?starts_at_after=2026-11-02&starts_at_after=2026-11-03")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_query"
        assert response.json()["error"]["details"][0]["field"] == "starts_at_after"

    @pytest.mark.parametrize(
        "value,field,detail_code,detail_message",
        [
            ("", "starts_at_after", "blank", "This field may not be blank."),
            ("2026-02-30", "starts_at_before", "invalid_format", "Enter a valid ISO date."),
            (
                "2026-11-02T12:00:00",
                "starts_at_after",
                "invalid_format",
                "Enter YYYY-MM-DD or an offset-aware RFC3339 datetime.",
            ),
            ("2026-11-02T12:00:00+24:00", "starts_at_before", "invalid_format", "Enter a valid RFC3339 UTC offset."),
        ],
    )
    def test_range_errors_keep_public_field_codes_and_messages(
        self, api_client, value, field, detail_code, detail_message
    ):
        response = api_client.get(URL, {field: value})
        assert response.status_code == 400
        self._assert_query_error(response, [{"field": field, "code": detail_code, "message": detail_message}])

    def test_blank_and_invalid_bounds_report_both_public_errors(self, api_client):
        response = api_client.get(URL, {"starts_at_after": "", "starts_at_before": "2026-02-30"})

        assert response.status_code == 400
        self._assert_query_error(
            response,
            [
                {"field": "starts_at_after", "code": "blank", "message": "This field may not be blank."},
                {"field": "starts_at_before", "code": "invalid_format", "message": "Enter a valid ISO date."},
            ],
        )

    @staticmethod
    def _assert_query_error(response, details):
        payload = response.json()
        assert set(payload) == {"error"}
        assert set(payload["error"]) == {"code", "message", "details", "request_id"}
        assert payload["error"]["code"] == "validation_failed"
        assert payload["error"]["message"] == "One or more fields are invalid."
        assert payload["error"]["details"] == details
        assert re.fullmatch(r"[0-9a-f]{32}", payload["error"]["request_id"])

    @pytest.mark.parametrize(
        "value,detail_code,detail_message",
        [
            ("", "blank", "This field may not be blank."),
            (" ", "invalid_format", "Enter YYYY-MM-DD or an offset-aware RFC3339 datetime."),
        ],
    )
    def test_temporal_blank_does_not_validate_unrelated_blank_query_filters(
        self, api_client, value, detail_code, detail_message
    ):
        query = {"creator": "", "status": "", "starts_at_after": value}
        response = api_client.get(URL, query)
        assert response.status_code == 400
        self._assert_query_error(
            response, [{"field": "starts_at_after", "code": detail_code, "message": detail_message}]
        )

    def test_equal_offset_instants_fail_on_public_before_field(self, api_client):
        response = api_client.get(
            URL,
            {"starts_at_after": "2026-11-02T07:00:00+07:00", "starts_at_before": "2026-11-02T00:00:00Z"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "validation_failed"
        assert response.json()["error"]["details"] == [
            {
                "field": "starts_at_before",
                "code": "invalid_range",
                "message": "Must be later than starts_at_after.",
            }
        ]

    def test_unknown_query_key_does_not_change_error_contract(self, api_client):
        response = api_client.get(URL, {"unexpected_window": "2026-11-02"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_query"
        assert response.json()["error"]["details"][0]["field"] == "unexpected_window"

    def test_booking_calendar_view_side_does_not_bypass_creator_scope(self, actor, make_booking):
        _role(actor, "user", 80107)
        lower = timezone.now() - timedelta(days=1)
        own = make_booking(starts_at=lower, ends_at=timezone.now() + timedelta(days=2))
        stranger = UserFactory(username="booking-calendar-stranger")
        hidden = make_booking(starts_at=lower, ends_at=timezone.now() + timedelta(days=2), status="cancelled")
        hidden.creator = stranger
        hidden.save(update_fields=["creator"])

        response = _client(actor).get(URL, {"view_side": "booking_calendar"})

        assert response.status_code == 200
        assert {item["id"] for item in response.json()["data"]} == {own.pk}

    def test_range_query_count_remains_bounded(self, actor, bench, project, make_booking, django_assert_num_queries):
        _role(actor, "user", 80108)
        starts_at = timezone.now() + timedelta(hours=1)
        for index in range(3):
            booking = make_booking(
                starts_at=starts_at + timedelta(hours=index * 2),
                ends_at=starts_at + timedelta(hours=index * 2 + 1),
            )
            booking.project = project
            booking.save(update_fields=["project"])

        with django_assert_num_queries(3):
            response = _client(actor).get(
                URL,
                {"starts_at_after": (starts_at - timedelta(minutes=1)).isoformat()},
            )
        assert response.status_code == 200
        assert len(response.json()["data"]) == 3

    def test_post_remains_available(self, api_client):
        response = api_client.options(URL)
        assert "POST" in response["Allow"]
        assert "GET" in response["Allow"]
