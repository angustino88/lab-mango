"""Review regressions; all persistence and transport boundaries are offline."""

import logging
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from config.settings.booking_notifications import notification_settings
from core.infrastructure import teams as teams_infrastructure
from core.labs.features.bench_bookings.application import notification_collection as collection
from core.labs.features.bench_bookings.application import notification_delivery as delivery
from core.labs.features.bench_bookings.application import notification_intents as intents
from core.labs.features.bench_bookings.contracts import BookingNotificationSnapshot
from core.labs.features.bench_bookings.integrations import notification_transport as transport
from core.labs.features.equipment.contracts import InactiveEquipmentSnapshot
from core.users import public as users

from .test_notifications import FLAGS, NOW, TEAMS_RECIPIENT, booking, notice


def start_notice():
    row = notice(kind="start")
    row.booking.starts_at = NOW - timedelta(minutes=1)
    row.booking.ends_at = NOW + timedelta(minutes=1)
    row.snapshot["starts_at"] = row.booking.starts_at.isoformat()
    row.snapshot["ends_at"] = row.booking.ends_at.isoformat()
    return row


@override_settings(**FLAGS)
def test_start_extension_uses_current_snapshot_and_shortening_suppresses():
    row = start_notice()
    row.booking.ends_at += timedelta(hours=1)
    assert delivery.reminder_is_current(row=row, now=NOW)
    assert delivery.send_snapshot(row).ends_at == row.booking.ends_at.isoformat()
    row.booking.ends_at = NOW
    assert not delivery.reminder_is_current(row=row, now=NOW)


@pytest.mark.parametrize("field,value", [("bench_id", 99), ("starts_at", NOW)])
@override_settings(**FLAGS)
def test_start_move_or_reschedule_invalidates_original(field, value):
    row = start_notice()
    setattr(row.booking, field, value)
    assert not delivery.reminder_is_current(row=row, now=NOW)


@override_settings(**FLAGS)
def test_start_cutoff_changed_between_collection_and_send():
    row = start_notice()
    with override_settings(BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF=NOW):
        assert not collection.start_eligible(booking=row.booking, now=NOW)
        assert delivery.delivery_precheck(row=row, now=NOW).code == "reminder_obsolete"


@override_settings(**FLAGS)
def test_locked_collection_rechecks_rescheduled_start_before_cutoff():
    item = booking(starts_at=NOW - timedelta(days=2))
    with (
        patch.object(collection.transaction, "atomic"),
        patch.object(collection.BenchBooking.objects, "filter") as query,
        patch.object(collection.BenchBooking.objects, "select_for_update") as locked,
        patch.object(collection, "inactive_equipment_candidates", return_value=[]),
        patch.object(collection, "record_notification") as record,
    ):
        query.return_value.order_by.return_value.values_list.return_value.__getitem__.return_value = [7]
        locked.return_value.select_related.return_value.get.return_value = item
        collection.collect_notifications(now=NOW)
        record.assert_not_called()


@override_settings(**FLAGS)
def test_start_intent_deadline_and_sent_dedupe_not_resurrected():
    item = booking(starts_at=NOW, ends_at=NOW + timedelta(minutes=1))
    with patch.object(
        intents.BookingNotification.objects, "get_or_create", return_value=(notice(state="sent"), False)
    ) as write:
        assert intents.record_notification(booking=item, kind="start", logical_key=NOW.isoformat(), now=NOW) == 0
        key = write.call_args.kwargs["dedupe_key"]
        assert write.call_args.kwargs["defaults"]["expires_at"] == NOW + timedelta(minutes=10)
        item.ends_at += timedelta(hours=1)
        assert intents.record_notification(booking=item, kind="start", logical_key=NOW.isoformat(), now=NOW) == 0
        assert write.call_args.kwargs["dedupe_key"] == key


@override_settings(**FLAGS)
def test_reason_not_in_payload_render_or_logs(caplog):
    marker = "SYNTHETIC_REASON_MUST_NOT_LEAVE_COMPARISON"
    item = booking(reason=marker)
    caplog.set_level(logging.DEBUG)
    with patch.object(intents.BookingNotification.objects, "get_or_create", return_value=(None, True)) as write:
        intents.record_notification(booking=item, kind="updated", now=NOW)
    payload = write.call_args.kwargs["defaults"]["snapshot"]
    assert marker not in str(payload)
    assert marker not in transport.notification_text(kind="updated", snapshot=BookingNotificationSnapshot(**payload))
    assert marker not in caplog.text


def test_deadline_claim_query_and_expired_reaper_are_separate():
    with (
        patch.object(delivery.transaction, "atomic"),
        patch.object(delivery.BookingNotification.objects, "select_for_update") as query,
    ):
        query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        assert delivery.claim_one(now=NOW) is None
        assert query.return_value.filter.call_args.kwargs["expires_at__gt"] == NOW
        query.return_value.filter.return_value.order_by.assert_called_once_with("expires_at", "available_at", "id")
        query.reset_mock()
        query.return_value.filter.return_value.order_by.return_value.values_list.return_value.__getitem__.return_value = []
        assert delivery.reap_expired(now=NOW, limit=1000) == 0
        assert query.return_value.filter.call_args.kwargs["expires_at__lte"] == NOW
        assert (
            query.return_value.filter.return_value.order_by.return_value.values_list.return_value.__getitem__.call_args.args[
                0
            ].stop
            == 100
        )
        predicate = query.return_value.filter.call_args.args[0]
        assert ("lease_until__lte", NOW) in predicate.children[1].children


@pytest.mark.parametrize("scenario", ["expiry", "lease_time", "token"])
@override_settings(**FLAGS)
def test_slow_precheck_rechecks_clock_and_token_before_transport(scenario):
    row = notice(kind="created")
    current_time = [NOW]

    def precheck(**kwargs):
        if scenario == "expiry":
            current_time[0] = row.expires_at
        elif scenario == "lease_time":
            current_time[0] = row.lease_until
        return None

    with (
        patch.object(delivery.timezone, "now", side_effect=lambda: current_time[0]),
        patch.object(delivery, "claim_one", side_effect=[row, None]),
        patch.object(delivery, "reap_expired", return_value=0),
        patch.object(delivery.BookingNotification.objects, "select_related") as reads,
        patch.object(delivery.BookingNotification.objects, "filter") as fence,
        patch.object(delivery, "delivery_precheck", side_effect=precheck),
        patch.object(delivery, "complete_claim", return_value=True),
        patch.object(delivery, "deliver") as send,
    ):
        reads.return_value.get.return_value = row
        fence.return_value.exists.return_value = scenario == "expiry"
        result = delivery.deliver_notifications()
        send.assert_not_called()
        assert fence.call_args.kwargs["lease_until__gt"] == current_time[0]
        assert fence.call_args.kwargs["lease_token"] == row.lease_token
        assert result["expired" if scenario == "expiry" else "fenced"] == 1


@override_settings(**FLAGS)
def test_slow_inactive_precheck_revalidates_episode_before_transport():
    row = notice(kind="inactive")
    candidate = InactiveEquipmentSnapshot(
        4, 3, "BOOK-SYNTHETIC", NOW - timedelta(minutes=61), NOW - timedelta(hours=2), "Clean Bench", "Microscope"
    )
    with (
        patch.object(delivery.timezone, "now", return_value=NOW),
        patch.object(delivery, "claim_one", side_effect=[row, None]),
        patch.object(delivery, "reap_expired", return_value=0),
        patch.object(delivery, "owns_lease", return_value=True),
        patch.object(delivery, "inactive_equipment_candidates", side_effect=[[candidate], []]),
        patch.object(delivery.BookingNotification.objects, "select_related") as reads,
        patch.object(delivery, "complete_claim", return_value=True),
        patch.object(delivery, "deliver") as send,
    ):
        reads.return_value.get.return_value = row
        result = delivery.deliver_notifications()
    send.assert_not_called()
    assert result["expired"] == 1


@pytest.mark.parametrize("binding", [None, "mismatch", "correct"])
def test_user_owned_resolver_never_uses_mutable_email(binding):
    identity = (
        None
        if binding is None
        else {
            "tenant_id": TEAMS_RECIPIENT.tenant_id if binding == "correct" else uuid.UUID(int=3),
            "object_id": TEAMS_RECIPIENT.object_id,
        }
    )
    with patch.object(users.EntraIdentity.objects, "filter") as query:
        query.return_value.values.return_value.first.return_value = identity
        result = users.resolve_teams_recipient(user_id=9, expected_tenant_id=TEAMS_RECIPIENT.tenant_id)
        assert result == (TEAMS_RECIPIENT if binding == "correct" else None)
        query.assert_called_once_with(user_id=9, user__is_active=True, tenant_id=TEAMS_RECIPIENT.tenant_id)


@pytest.mark.parametrize("binding", [None, "mismatch", "correct"])
@override_settings(**FLAGS)
def test_delivery_uses_verified_tenant_and_object_ids_only(binding):
    row = notice(kind="created", channel="teams")
    identity = TEAMS_RECIPIENT if binding == "correct" else None
    with (
        patch.object(delivery.timezone, "now", return_value=NOW),
        patch.object(delivery, "claim_one", side_effect=[row, None]),
        patch.object(delivery, "reap_expired", return_value=0),
        patch.object(delivery, "owns_lease", return_value=True),
        patch.object(delivery, "resolve_teams_recipient", return_value=identity),
        patch.object(delivery.BookingNotification.objects, "select_related") as reads,
        patch.object(delivery, "complete_claim", return_value=True),
        patch.object(delivery, "deliver", return_value=transport.DeliveryOutcome("sent", "accepted")) as send,
    ):
        reads.return_value.get.return_value = row
        result = delivery.deliver_notifications()

    if identity is None:
        assert result["skipped"] == 1
        send.assert_not_called()
    else:
        assert result["sent"] == 1
        assert send.call_args.kwargs["teams_recipient"] == TEAMS_RECIPIENT


@override_settings(**FLAGS)
def test_missing_teams_binding_skips_only_teams_email_still_sent():
    rows = [notice(kind="created", channel="teams"), notice(kind="created", channel="email")]
    with (
        patch.object(delivery.timezone, "now", return_value=NOW),
        patch.object(delivery, "claim_one", side_effect=[*rows, None]),
        patch.object(delivery, "reap_expired", return_value=0),
        patch.object(delivery, "owns_lease", return_value=True),
        patch.object(delivery, "resolve_teams_recipient", return_value=None),
        patch.object(delivery.BookingNotification.objects, "select_related") as reads,
        patch.object(delivery, "complete_claim", return_value=True),
        patch.object(delivery, "deliver", return_value=transport.DeliveryOutcome("sent", "accepted")) as send,
    ):
        reads.return_value.get.side_effect = rows
        result = delivery.deliver_notifications()
        assert result["skipped"] == result["sent"] == 1
        assert send.call_args.kwargs["channel"] == "email"
        assert send.call_count == 1


def test_workflow_connectionpool_logs_suppressed_before_request(caplog):
    marker = "SYNTHETIC_WORKFLOW_URL_MARKER"
    caplog.set_level(logging.DEBUG)

    def post(*args, **kwargs):
        for name in ("urllib3.connectionpool", "requests.packages.urllib3.connectionpool"):
            logging.getLogger(name).debug("request target %s", marker)
            logging.getLogger(name).warning("request target %s", marker)
        return MagicMock(status_code=202)

    with patch.object(teams_infrastructure.service.requests, "Session") as factory:
        factory.return_value.__enter__.return_value.post.side_effect = post
        transport.deliver(
            channel="teams",
            recipient="",
            event_id=uuid.uuid4(),
            kind="created",
            snapshot=BookingNotificationSnapshot(**notice().snapshot),
            teams_recipient=TEAMS_RECIPIENT,
        )
    assert marker not in caplog.text
    transport.protect_workflow_logs()
    assert logging.getLogger("urllib3.connectionpool").filters.count(transport._WORKFLOW_LOG_FILTER) == 1


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "100.64.0.1",
        "[::1]",
        "[fc00::1]",
        "[fe80::1]",
        "[::ffff:10.0.0.1]",
        "[::ffff:127.0.0.1]",
    ],
)
def test_non_global_ip_literal_rejected_even_when_allowlisted(host):
    env = MagicMock()
    env.bool.return_value = True
    env.list.return_value = [host.strip("[]")]
    values = {
        "BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF": NOW.isoformat(),
        "BOOKING_NOTIFICATIONS_TEAMS_WORKFLOW_URL": "https://" + host + "/synthetic",
        "BOOKING_NOTIFICATIONS_TEAMS_EXPECTED_TENANT_ID": str(TEAMS_RECIPIENT.tenant_id),
    }
    env.side_effect = lambda name, default: values.get(name, default)
    with pytest.raises(ImproperlyConfigured, match="HTTPS"):
        notification_settings(env)


def test_expected_tenant_required_and_validated():
    env = MagicMock()
    env.bool.return_value = True
    env.list.return_value = ["workflow.example.invalid"]
    values = {
        "BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF": NOW.isoformat(),
        "BOOKING_NOTIFICATIONS_TEAMS_WORKFLOW_URL": "https://workflow.example.invalid/synthetic",
    }
    env.side_effect = lambda name, default: values.get(name, default)
    with pytest.raises(ImproperlyConfigured, match="expected tenant"):
        notification_settings(env)
    values["BOOKING_NOTIFICATIONS_TEAMS_EXPECTED_TENANT_ID"] = "invalid"
    with pytest.raises(ImproperlyConfigured, match="UUID"):
        notification_settings(env)
    values["BOOKING_NOTIFICATIONS_TEAMS_EXPECTED_TENANT_ID"] = str(TEAMS_RECIPIENT.tenant_id)
    assert notification_settings(env)["BOOKING_NOTIFICATIONS_TEAMS_EXPECTED_TENANT_ID"] == TEAMS_RECIPIENT.tenant_id


@override_settings(**FLAGS)
def test_collector_time_budget_returns_last_committed_checkpoint():
    with (
        patch.object(collection, "monotonic", side_effect=[0, 1, 36]),
        patch.object(collection.transaction, "atomic"),
        patch.object(collection.BenchBooking.objects, "filter") as query,
        patch.object(collection.BenchBooking.objects, "select_for_update") as locked,
        patch.object(collection, "record_notification", return_value=2) as record,
        patch.object(collection, "inactive_equipment_candidates") as equipment,
    ):
        query.return_value.order_by.return_value.values_list.return_value.__getitem__.return_value = [7, 8]
        locked.return_value.select_related.return_value.get.return_value = booking(starts_at=NOW)
        result = collection.collect_notifications(now=NOW)
        assert result == {"created": 2, "booking_cursor": 7, "equipment_cursor": 0}
        assert record.call_count == 1
        equipment.assert_not_called()
