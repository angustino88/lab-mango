"""Deterministic isolated tests: mocked persistence and transports, no real database."""

import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.template.loader import render_to_string
from django.test import override_settings

from config.settings.booking_notifications import notification_settings
from core.infrastructure.teams.service import TeamsPostCode, TeamsPostResult, TeamsProxyPolicy
from core.labs.features.bench_bookings.application import notification_collection as collection
from core.labs.features.bench_bookings.application import notification_delivery as delivery
from core.labs.features.bench_bookings.application import notification_intents as intents
from core.labs.features.bench_bookings.contracts import BookingNotificationSnapshot, scheduled_start_is_due
from core.labs.features.bench_bookings.integrations import notification_transport as transport
from core.labs.features.equipment.contracts import InactiveEquipmentSnapshot
from core.labs.features.equipment.queries import inactivity_notifications as equipment_query
from core.labs.models import BookingNotification
from core.users.public import VerifiedTeamsRecipient

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
TEAMS_RECIPIENT = VerifiedTeamsRecipient(uuid.UUID(int=1), uuid.UUID(int=2))
FLAGS = {
    "BOOKING_NOTIFICATIONS_ENABLED": True,
    "BOOKING_NOTIFICATIONS_EMAIL_ENABLED": True,
    "BOOKING_NOTIFICATIONS_TEAMS_ENABLED": True,
    "BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF": NOW - timedelta(days=1),
}


def booking(**changes):
    values = dict(
        pk=7,
        creator_id=9,
        creator=SimpleNamespace(pk=9, is_active=True, email="owner@example.invalid"),
        booking_code="BOOK-SYNTHETIC",
        bench_id=3,
        starts_at=NOW - timedelta(minutes=90),
        ends_at=NOW + timedelta(hours=1),
        status="in_progress",
        approval_status="approved",
        project_id=None,
        reason="original synthetic reason",
    )
    return SimpleNamespace(**(values | changes))


def notice(**changes):
    resource_booking = booking()
    snapshot = BookingNotificationSnapshot(
        booking_code=resource_booking.booking_code,
        bench_id=3,
        starts_at=resource_booking.starts_at.isoformat(),
        ends_at=resource_booking.ends_at.isoformat(),
        status="in_progress",
        approval_status="approved",
        equipment_id=4,
        bench_name="Clean Bench",
        equipment_name="Microscope",
        inactive_at=(NOW - timedelta(minutes=61)).isoformat(),
    ).as_payload()
    values = dict(
        pk=uuid.uuid4(),
        event_id=uuid.uuid4(),
        state="leased",
        lease_token=uuid.uuid4(),
        lease_until=NOW + timedelta(seconds=120),
        expires_at=NOW + timedelta(minutes=10),
        created_at=NOW,
        attempts=1,
        snapshot=snapshot,
        kind="inactive",
        booking=resource_booking,
        recipient_id=9,
        recipient=resource_booking.creator,
        channel="email",
    )
    return SimpleNamespace(**(values | changes))


@pytest.mark.parametrize("seconds,expected", [(-1, False), (0, True), (599, True), (600, False)])
def test_start_half_open_window(seconds, expected):
    assert (
        scheduled_start_is_due(starts_at=NOW, ends_at=NOW + timedelta(hours=1), now=NOW + timedelta(seconds=seconds))
        is expected
    )


@override_settings(**FLAGS)
def test_start_ends_boundary_and_no_lifecycle_mutation():
    item = booking(starts_at=NOW, ends_at=NOW + timedelta(minutes=2), status="reserved")
    assert collection.start_eligible(booking=item, now=NOW)
    assert not collection.start_eligible(booking=item, now=item.ends_at)
    assert item.status == "reserved"
    item.approval_status = "pending"
    assert not collection.start_eligible(booking=item, now=NOW)


@override_settings(**FLAGS)
def test_dedupe_independent_channels_and_snapshot_allowlist():
    with patch.object(intents.BookingNotification.objects, "get_or_create") as write:
        write.side_effect = [(None, True), (None, True), (None, False), (None, False)]
        item = booking()
        assert intents.record_notification(booking=item, kind="start", logical_key="start", now=NOW) == 2
        assert intents.record_notification(booking=item, kind="start", logical_key="start", now=NOW) == 0
    first, second, repeated, _ = [call.kwargs for call in write.call_args_list]
    assert first["dedupe_key"] == repeated["dedupe_key"] != second["dedupe_key"]
    assert first["defaults"]["event_id"] == second["defaults"]["event_id"]
    assert first["defaults"]["recipient"] is item.creator
    assert set(first["defaults"]["snapshot"]) == {
        "booking_code",
        "bench_id",
        "starts_at",
        "ends_at",
        "status",
        "approval_status",
        "equipment_id",
        "inactive_at",
        "bench_name",
        "equipment_name",
    }


@override_settings(**FLAGS)
def test_created_event_deduplicates_repeated_hook_for_same_material_state():
    item = booking()
    with patch.object(intents.BookingNotification.objects, "get_or_create") as write:
        write.side_effect = [(None, True), (None, True), (None, False), (None, False)]
        assert intents.record_notification(booking=item, kind="created", now=NOW) == 2
        assert intents.record_notification(booking=item, kind="created", now=NOW) == 0
    first, second, repeated, _ = [call.kwargs for call in write.call_args_list]
    assert first["dedupe_key"] == repeated["dedupe_key"]
    assert first["defaults"]["event_id"] == repeated["defaults"]["event_id"]
    item.ends_at += timedelta(minutes=1)
    with patch.object(intents.BookingNotification.objects, "get_or_create") as write:
        write.side_effect = [(None, True), (None, True)]
        assert intents.record_notification(booking=item, kind="updated", now=NOW) == 2
    changed = write.call_args_list[0].kwargs
    assert changed["defaults"]["event_id"] != first["defaults"]["event_id"]


@pytest.mark.parametrize(
    "changes",
    [
        {"creator_id": None},
        {"creator": SimpleNamespace(is_active=False, email="owner@example.invalid")},
    ],
)
@override_settings(**FLAGS)
def test_unavailable_recipient_never_records(changes):
    with patch.object(intents.BookingNotification.objects, "get_or_create") as write:
        assert intents.record_notification(booking=booking(**changes), kind="created", now=NOW) == 0
        write.assert_not_called()


def test_disabled_and_future_cutoff_do_not_query():
    with patch.object(intents.BookingNotification.objects, "get_or_create") as write:
        assert intents.record_notification(booking=booking(), kind="created", now=NOW) == 0
        with override_settings(**(FLAGS | {"BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF": NOW + timedelta(seconds=1)})):
            assert intents.record_notification(booking=booking(), kind="created", now=NOW) == 0
        write.assert_not_called()


def test_material_comparison_excludes_reason():
    item = booking()
    before = intents.material_values(item)
    assert intents.material_values(item) == before
    item.reason = "Synthetic free text"
    assert intents.material_values(item) == before
    before = intents.material_values(item)
    item.reason = "Synthetic free text"
    assert intents.material_values(item) == before
    item.ends_at += timedelta(minutes=1)
    assert intents.material_values(item) != before


def test_private_teams_contract_and_timeouts():
    result_from_common = TeamsPostResult(True, False, TeamsPostCode.ACCEPTED, 202)
    with patch.object(transport, "post_teams_json", return_value=result_from_common) as post:
        row = notice()
        result = transport.deliver(
            channel="teams",
            recipient="owner@example.invalid",
            event_id=row.event_id,
            kind="start",
            snapshot=BookingNotificationSnapshot(**row.snapshot),
            teams_recipient=TEAMS_RECIPIENT,
        )
        assert result.state == "sent"
        post.assert_called_once()
        args, kwargs = post.call_args
        assert args[0] == transport.settings.BOOKING_NOTIFICATIONS_TEAMS_WORKFLOW_URL
        payload = args[1]
        assert kwargs == {"timeout": (3.0, 5.0), "proxy_policy": TeamsProxyPolicy.DISABLED}
        assert payload["recipient_tenant_id"] == str(TEAMS_RECIPIENT.tenant_id)
        assert payload["recipient_object_id"] == str(TEAMS_RECIPIENT.object_id)
        assert "recipient_upn" not in payload
        assert payload["event_id"] == str(row.event_id)
        assert "Scheduled booking time has arrived" in payload["text"]
        assert "channel" not in payload
        assert set(payload) == {"event_id", "recipient_tenant_id", "recipient_object_id", "text"}
        assert "Clean Bench" in payload["text"]
        assert "7" not in payload["text"]
        assert "Bench resource" not in payload["text"]
        assert "Computing resource" not in payload["text"]


def test_inactive_teams_text_uses_friendly_names_without_numeric_ids():
    row = notice(kind="inactive")
    with patch.object(
        transport,
        "post_teams_json",
        return_value=TeamsPostResult(True, False, TeamsPostCode.ACCEPTED, 202),
    ) as post:
        result = transport.deliver(
            channel="teams",
            recipient="owner@example.invalid",
            event_id=row.event_id,
            kind="inactive",
            snapshot=BookingNotificationSnapshot(**row.snapshot),
            teams_recipient=TEAMS_RECIPIENT,
        )
    assert result.state == "sent"
    text = post.call_args.args[1]["text"]
    assert "Equipment inactivity reminder (over 60 minutes)" in text
    assert "Clean Bench" in text and "Microscope" in text
    assert re.search(r"\b(?:3|4)\b", text) is None
    assert "Computing resource" not in text


@pytest.mark.parametrize(
    "common_result,expected",
    [
        (TeamsPostResult(False, True, TeamsPostCode.RETRYABLE_TRANSPORT), ("retry", "network_transient")),
        (TeamsPostResult(False, True, TeamsPostCode.RETRYABLE_HTTP, 503), ("retry", "http_transient")),
        (TeamsPostResult(False, False, TeamsPostCode.HTTP_FAILED, 400), ("failed", "http_permanent")),
        (TeamsPostResult(False, False, TeamsPostCode.REQUEST_FAILED), ("failed", "transport_configuration")),
    ],
)
def test_teams_outcomes_map_to_booking_delivery_state(common_result, expected):
    with patch.object(transport, "post_teams_json", return_value=common_result):
        result = transport.deliver(
            channel="teams",
            recipient="owner@example.invalid",
            event_id=uuid.uuid4(),
            kind="created",
            snapshot=BookingNotificationSnapshot(**notice().snapshot),
            teams_recipient=TEAMS_RECIPIENT,
        )
        assert (result.state, result.code) == expected


def test_missing_verified_teams_identity_skips_shared_transport():
    with patch.object(transport, "post_teams_json") as post:
        result = transport.deliver(
            channel="teams",
            recipient="owner@example.invalid",
            event_id=uuid.uuid4(),
            kind="created",
            snapshot=BookingNotificationSnapshot(**notice().snapshot),
        )
    assert (result.state, result.code) == ("skipped", "teams_identity_unavailable")
    post.assert_not_called()


def test_email_sender_failure_maps_to_retry():
    with (
        patch.object(transport, "send_email", return_value=False) as send_email,
    ):
        result = transport.deliver(
            channel="email",
            recipient="owner@example.invalid",
            event_id=uuid.uuid4(),
            kind="created",
            snapshot=BookingNotificationSnapshot(**notice().snapshot),
        )
        send_email.assert_called_once()
        assert result.state == "retry"


def test_email_uses_existing_html_sender_and_allowlisted_context():
    row = notice(kind="start")
    snapshot = BookingNotificationSnapshot(**row.snapshot)
    with patch.object(transport, "send_email", return_value=True) as send_email:
        result = transport.deliver(
            channel="email",
            recipient="owner@example.invalid",
            event_id=row.event_id,
            kind="start",
            snapshot=snapshot,
        )
    assert result.state == "sent"
    args = send_email.call_args.kwargs
    assert args["template"] == "emails/booking_confirmation.html"
    assert args["receivers"] == ["owner@example.invalid"]
    assert args["log_failure_details"] is False
    assert args["context"]["action"] == "notification"
    assert args["context"]["notification_heading"] == "Scheduled booking time has arrived"
    assert args["context"]["snapshot"] == snapshot
    assert "booking" not in args["context"]
    assert "booking_url" not in args["context"]
    assert args["context"]["event_id"] == str(row.event_id)


def test_booking_email_template_renders_html_snapshot_without_free_text():
    snapshot = BookingNotificationSnapshot(**notice().snapshot)
    rendered = render_to_string(
        "emails/booking_confirmation.html",
        transport.notification_email_context(kind="inactive", snapshot=snapshot, event_id=uuid.uuid4()),
    )

    assert "<table" in rendered.lower()
    assert "BOOK-SYNTHETIC" in rendered
    assert "Equipment inactivity reminder (over 60 minutes)" in rendered
    assert "This message does not change the booking or equipment status" in rendered
    assert "No activity has been reported for the assigned equipment for more than 60 minutes" in rendered
    assert "view booking details" not in rendered.lower()
    assert "Clean Bench" in rendered and "Microscope" in rendered
    assert "Bench ID" not in rendered and "Equipment ID" not in rendered
    assert "Lab Management System" not in rendered
    assert "computing" not in rendered.lower()
    assert "Bench resource" not in rendered and "Computing resource" not in rendered
    assert re.search(r"\b(?:7|19)\b", rendered) is None
    assert "original synthetic reason" not in rendered


@override_settings(**FLAGS)
def test_inactive_revalidation_matches_resource_episode():
    row = notice()
    candidate = InactiveEquipmentSnapshot(
        4, 3, "BOOK-SYNTHETIC", NOW - timedelta(minutes=61), NOW - timedelta(hours=2), "Clean Bench", "Microscope"
    )
    with patch.object(delivery, "inactive_equipment_candidates", return_value=[candidate]):
        assert delivery.reminder_is_current(row=row, now=NOW)
        row.booking.starts_at = NOW - timedelta(minutes=60)
        assert not delivery.reminder_is_current(row=row, now=NOW)
        row.booking.starts_at = NOW - timedelta(minutes=90)
        row.booking.bench_id = 10
        assert not delivery.reminder_is_current(row=row, now=NOW)
    with patch.object(delivery, "inactive_equipment_candidates", return_value=[]):
        assert not delivery.reminder_is_current(row=row, now=NOW)


@override_settings(**FLAGS)
def test_stale_start_owner_and_expiry_prechecks():
    row = notice(kind="start")
    assert delivery.delivery_precheck(row=row, now=NOW).state == "expired"
    row.kind = "created"
    row.recipient_id = 12
    assert delivery.delivery_precheck(row=row, now=NOW).state == "skipped"
    row.recipient_id = 9
    row.expires_at = NOW
    assert delivery.delivery_precheck(row=row, now=NOW).state == "expired"


def test_equipment_query_strict_sixty_and_fresh_heartbeat_filters():
    with patch.object(equipment_query.ComputingActivity.objects, "filter") as query:
        query.return_value.exclude.return_value.order_by.return_value.values.return_value.__getitem__.return_value = []
        assert equipment_query.inactive_equipment_candidates(now=NOW) == []
        filters = query.call_args.kwargs
        assert filters["inactive_at__lt"] == NOW - timedelta(minutes=60)
        assert filters["last_agent_report_at__gte"] == NOW - timedelta(minutes=10)
        assert filters["last_agent_report_at__lte"] == NOW
        assert filters["computing__bench_assignments__unassigned_at__isnull"] is True
        assert filters["computing__bench_assignments__assigned_at__lte"].name == "inactive_at"


def test_retry_bounds_and_token_fencing():
    assert delivery.retry_delay(attempt=1, jitter=0) == timedelta(seconds=30)
    assert delivery.retry_delay(attempt=5, jitter=1) == timedelta(seconds=960)
    row = notice(attempts=5)
    with patch.object(delivery.BookingNotification.objects, "filter") as query:
        query.return_value.update.return_value = 0
        assert not delivery.complete_claim(
            row=row, result=transport.DeliveryOutcome("retry", "http_transient"), now=NOW
        )
        assert query.call_args.kwargs["lease_token"] == row.lease_token
        assert query.call_args.kwargs["lease_until__gt"] == NOW
        assert query.return_value.update.call_args.kwargs["state"] == "failed"


def test_claim_uses_skip_locked_recovers_expired_lease():
    row = notice(attempts=2, lease_until=NOW - timedelta(seconds=1))
    row.save = MagicMock()
    with (
        patch.object(delivery.transaction, "atomic"),
        patch.object(delivery.BookingNotification.objects, "select_for_update") as query,
    ):
        query.return_value.filter.return_value.order_by.return_value.first.return_value = row
        original_token = row.lease_token
        assert delivery.claim_one(now=NOW) is row
        query.assert_called_once_with(skip_locked=True)
        assert row.attempts == 3 and row.lease_token != original_token
        assert row.lease_until == NOW + timedelta(seconds=120)


def test_claim_exhausted_never_sends():
    row = notice(attempts=5)
    row.save = MagicMock()
    with (
        patch.object(delivery.transaction, "atomic"),
        patch.object(delivery.BookingNotification.objects, "select_for_update") as query,
    ):
        query.return_value.filter.return_value.order_by.return_value.first.return_value = row
        assert delivery.claim_one(now=NOW).state == "failed"
        assert row.lease_token is None


def test_database_constraints_present():
    assert BookingNotification._meta.get_field("dedupe_key").unique
    assert {constraint.name for constraint in BookingNotification._meta.constraints} == {
        "booking_notice_one_booking",
        "booking_notice_channel",
        "booking_notice_kind",
        "booking_notice_state",
        "booking_notice_lease",
    }


def test_configuration_fail_closed_and_utc():
    env = MagicMock()
    env.bool.side_effect = lambda name, default: False
    env.side_effect = lambda name, default: default
    env.list.return_value = []
    assert notification_settings(env)["BOOKING_NOTIFICATIONS_ENABLED"] is False
    env.bool.side_effect = lambda name, default: name == "BOOKING_NOTIFICATIONS_ENABLED"
    from django.core.exceptions import ImproperlyConfigured

    with pytest.raises(ImproperlyConfigured, match="UTC enablement cutoff"):
        notification_settings(env)


@pytest.mark.parametrize("cutoff", ["invalid", "2026-10-20T12:00:00", "2026-10-20T12:00:00+01:00"])
def test_configuration_rejects_invalid_or_non_utc_cutoff(cutoff):
    from django.core.exceptions import ImproperlyConfigured

    env = MagicMock()
    env.bool.return_value = True
    env.side_effect = lambda name, default: cutoff if name == "BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF" else default
    with pytest.raises(ImproperlyConfigured, match="UTC timestamp"):
        notification_settings(env)


def test_configuration_rejects_unapproved_workflow_host_without_echoing_url():
    from django.core.exceptions import ImproperlyConfigured

    env = MagicMock()
    env.bool.return_value = True
    env.list.return_value = ["approved.example.invalid"]
    values = {
        "BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF": "2026-10-20T00:00:00Z",
        "BOOKING_NOTIFICATIONS_TEAMS_WORKFLOW_URL": "https://unapproved.example.invalid/synthetic-secret",
    }
    env.side_effect = lambda name, default: values.get(name, default)
    with pytest.raises(ImproperlyConfigured) as error:
        notification_settings(env)
    assert "synthetic-secret" not in str(error.value)
