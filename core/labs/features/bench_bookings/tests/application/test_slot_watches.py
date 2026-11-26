"""Slot watches: commands, availability decisions, collection and delivery over email, Teams and web."""

from datetime import timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

import pytest
from django.utils import timezone

from core.common.notifications import DeliveryOutcome
from core.labs.features.bench_bookings.application.slot_watch_collection import (
    collect_slot_watch_notifications,
    free_intervals,
)
from core.labs.features.bench_bookings.application.slot_watch_delivery import deliver_slot_watch_notifications
from core.labs.features.bench_bookings.application.slot_watches import (
    MAX_ACTIVE_WATCHES_PER_USER,
    CreateSlotWatchInput,
    SlotWatchInvalid,
    cancel_slot_watch,
    create_slot_watch,
)
from core.labs.features.bench_bookings.exceptions import BenchBookingPermissionDenied
from core.labs.models import (
    BenchBooking,
    BenchSlotNotification,
    BenchSlotWatch,
    BookingApprovalStatus,
    BookingStatus,
    SlotWatchStatus,
)
from core.users.tests.factories import UserFactory
from core.websocket.models import Notification

ALL_CHANNELS = {
    "BOOKING_SLOT_WATCH_ENABLED": True,
    "BOOKING_NOTIFICATIONS_ENABLED": True,
    "BOOKING_NOTIFICATIONS_EMAIL_ENABLED": True,
    "BOOKING_NOTIFICATIONS_TEAMS_ENABLED": True,
}
H = timedelta(hours=1)
M = timedelta(minutes=1)


@pytest.fixture()
def watcher(db):
    from tests.factories import grant_labs_role

    return grant_labs_role(UserFactory(username="slot-watcher", email="watcher@example.invalid"), "member")


@pytest.fixture()
def enabled(settings):
    for key, value in ALL_CHANNELS.items():
        setattr(settings, key, value)
    settings.BOOKING_SLOT_WATCH_LEAD_MINUTES = 15
    return settings


@pytest.fixture()
def watch_for(watcher, bench):
    def _make(start, end, *, web_only=False, settings=None):
        if web_only:
            settings.BOOKING_NOTIFICATIONS_ENABLED = False
        data = CreateSlotWatchInput(bench_id=bench.pk, range_start=start, range_end=end)
        watch = create_slot_watch(actor=watcher, data=data, now=start - H if start > timezone.now() else None)
        # Watches are created "before" the bookings change in these scenarios.
        BenchSlotWatch.objects.filter(pk=watch.pk).update(created=timezone.now() - H)
        watch.refresh_from_db()
        return watch

    return _make


def _cancel(booking):
    booking.status = BookingStatus.CANCELLED
    booking.cancellation_reason = "plans changed"
    booking.save(update_fields=("status", "cancellation_reason", "modified"))


# --- free_intervals (pure) -------------------------------------------------------------------


def test_free_intervals_finds_gaps_between_busy_ranges(now):
    window = (now, now + 4 * H)
    busy = [(now - H, now + H), (now + 2 * H, now + 3 * H)]
    assert free_intervals(window, busy) == [(now + H, now + 2 * H), (now + 3 * H, now + 4 * H)]


def test_free_intervals_ignores_tiny_gaps_and_full_cover(now):
    assert free_intervals((now, now + H), [(now, now + H)]) == []
    assert free_intervals((now, now + H), [(now + 2 * M, now + H)]) == []  # 2-minute gap is below the minimum


# --- commands --------------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreateAndCancel:
    def test_create_is_idempotent_for_same_range(self, watcher, bench, now):
        data = CreateSlotWatchInput(bench_id=bench.pk, range_start=now + H, range_end=now + 2 * H)
        first = create_slot_watch(actor=watcher, data=data)
        again = create_slot_watch(actor=watcher, data=data)
        assert first.pk == again.pk
        assert BenchSlotWatch.objects.count() == 1

    @pytest.mark.parametrize(
        ("start", "end", "field"),
        [
            (2, 1, "range_end"),
            (-3, -1, "range_end"),
            (1, 1 + 24 * 8, "range_end"),
            (24 * 61, 24 * 62, "range_start"),
        ],
    )
    def test_invalid_input_is_rejected(self, watcher, bench, now, start, end, field):
        data = CreateSlotWatchInput(bench_id=bench.pk, range_start=now + start * H, range_end=now + end * H)
        with pytest.raises(SlotWatchInvalid) as error:
            create_slot_watch(actor=watcher, data=data, now=now)
        assert field in error.value.details

    def test_active_watch_cap(self, watcher, bench, now):
        for i in range(MAX_ACTIVE_WATCHES_PER_USER):
            create_slot_watch(
                actor=watcher,
                data=CreateSlotWatchInput(
                    bench_id=bench.pk, range_start=now + (i + 1) * H, range_end=now + (i + 2) * H
                ),
            )
        with pytest.raises(SlotWatchInvalid):
            create_slot_watch(
                actor=watcher,
                data=CreateSlotWatchInput(bench_id=bench.pk, range_start=now + 50 * H, range_end=now + 51 * H),
            )

    def test_anonymous_actor_is_refused(self, bench, now):
        with pytest.raises(BenchBookingPermissionDenied):
            create_slot_watch(
                actor=None, data=CreateSlotWatchInput(bench_id=bench.pk, range_start=now + H, range_end=now + 2 * H)
            )

    def test_cancel_is_owner_only_and_repeatable(self, watcher, actor, bench, now):
        watch = create_slot_watch(
            actor=watcher, data=CreateSlotWatchInput(bench_id=bench.pk, range_start=now + H, range_end=now + 2 * H)
        )
        with pytest.raises(BenchSlotWatch.DoesNotExist):
            cancel_slot_watch(actor=actor, watch_id=watch.pk)
        assert cancel_slot_watch(actor=watcher, watch_id=watch.pk).status == SlotWatchStatus.CANCELLED
        assert cancel_slot_watch(actor=watcher, watch_id=watch.pk).status == SlotWatchStatus.CANCELLED


# --- collection ------------------------------------------------------------------------------


@pytest.mark.django_db
class TestCollection:
    def test_disabled_feature_collects_nothing(self, settings, watch_for, make_booking, now):
        settings.BOOKING_SLOT_WATCH_ENABLED = False
        watch_for(now, now + 2 * H)
        make_booking(starts_at=now - H, ends_at=now + 10 * M, status=BookingStatus.IN_PROGRESS)
        assert collect_slot_watch_notifications(now=now)["created"] == 0

    def test_ending_soon_queues_every_channel_once(self, enabled, watch_for, make_booking, now):
        watch = watch_for(now, now + 2 * H)
        make_booking(starts_at=now - H, ends_at=now + 10 * M, status=BookingStatus.IN_PROGRESS)
        assert collect_slot_watch_notifications(now=now)["created"] == 3
        assert collect_slot_watch_notifications(now=now + M)["created"] == 0  # durable dedupe
        rows = BenchSlotNotification.objects.filter(watch=watch)
        assert {r.channel for r in rows} == {"email", "teams", "in_app"}
        assert {r.kind for r in rows} == {"slot_ending_soon"}
        snapshot = rows.first().snapshot
        assert snapshot["free_from"] == (now + 10 * M).astimezone(dt_timezone.utc).isoformat()
        assert "booking_code" not in snapshot  # the other user's booking is never disclosed

    def test_ending_outside_lead_time_is_not_news(self, enabled, watch_for, make_booking, now):
        watch_for(now, now + 3 * H)
        make_booking(starts_at=now - H, ends_at=now + H, status=BookingStatus.IN_PROGRESS)
        assert collect_slot_watch_notifications(now=now)["created"] == 0

    def test_ending_soon_with_back_to_back_booking_is_not_free(self, enabled, watch_for, make_booking, now):
        watch_for(now, now + 2 * H)
        make_booking(starts_at=now - H, ends_at=now + 10 * M, status=BookingStatus.IN_PROGRESS)
        make_booking(starts_at=now + 10 * M, ends_at=now + 3 * H)
        assert collect_slot_watch_notifications(now=now)["created"] == 0

    def test_cancelled_booking_frees_the_slot(self, enabled, watch_for, make_booking, now):
        watch_for(now + H, now + 3 * H, web_only=True, settings=enabled)
        booking = make_booking(starts_at=now + H, ends_at=now + 2 * H)
        assert collect_slot_watch_notifications(now=now)["created"] == 0
        _cancel(booking)
        assert collect_slot_watch_notifications(now=now)["created"] == 1
        row = BenchSlotNotification.objects.get()
        assert row.kind == "slot_freed" and row.channel == "in_app"

    def test_early_completion_frees_the_rest_of_the_booking(self, enabled, watch_for, make_booking, now):
        watch_for(now, now + 2 * H, web_only=True, settings=enabled)
        booking = make_booking(starts_at=now - H, ends_at=now + H, status=BookingStatus.IN_PROGRESS)
        booking.status = BookingStatus.COMPLETED
        booking.completed_at = now
        booking.save(update_fields=("status", "completed_at", "modified"))
        assert collect_slot_watch_notifications(now=now)["created"] == 1
        assert BenchSlotNotification.objects.get().snapshot["free_from"] == now.astimezone(dt_timezone.utc).isoformat()

    def test_rejected_pending_booking_frees_the_slot(self, enabled, watch_for, make_booking, now):
        watch_for(now + H, now + 3 * H, web_only=True, settings=enabled)
        booking = make_booking(starts_at=now + H, ends_at=now + 2 * H)
        booking.approval_status = BookingApprovalStatus.REJECTED
        booking.rejection_reason = "not this week"
        booking.save(update_fields=("approval_status", "rejection_reason", "modified"))
        assert collect_slot_watch_notifications(now=now)["created"] == 1

    def test_release_before_the_watch_existed_is_ignored(self, enabled, watcher, bench, make_booking, now):
        booking = make_booking(starts_at=now + H, ends_at=now + 2 * H)
        _cancel(booking)
        create_slot_watch(
            actor=watcher,
            data=CreateSlotWatchInput(bench_id=bench.pk, range_start=now + H, range_end=now + 3 * H),
        )
        assert collect_slot_watch_notifications(now=timezone.now())["created"] == 0

    def test_own_booking_is_ignored(self, enabled, watch_for, watcher, bench, now):
        watch_for(now, now + 2 * H)
        BenchBooking(
            bench=bench,
            starts_at=now - H,
            ends_at=now + 10 * M,
            status=BookingStatus.IN_PROGRESS,
            booking_code="OWN-0001",
        ).save(actor=watcher)
        assert collect_slot_watch_notifications(now=now)["created"] == 0

    def test_email_and_teams_need_booking_notification_switches(self, enabled, watch_for, make_booking, now):
        enabled.BOOKING_NOTIFICATIONS_ENABLED = False
        watch_for(now, now + 2 * H)
        make_booking(starts_at=now - H, ends_at=now + 10 * M, status=BookingStatus.IN_PROGRESS)
        collect_slot_watch_notifications(now=now)
        assert list(BenchSlotNotification.objects.values_list("channel", flat=True)) == ["in_app"]

    def test_finished_watches_expire(self, enabled, watcher, bench, now):
        watch = create_slot_watch(
            actor=watcher, data=CreateSlotWatchInput(bench_id=bench.pk, range_start=now + H, range_end=now + 2 * H)
        )
        assert collect_slot_watch_notifications(now=now + 3 * H)["expired_watches"] == 1
        watch.refresh_from_db()
        assert watch.status == SlotWatchStatus.EXPIRED


# --- delivery --------------------------------------------------------------------------------


@pytest.mark.django_db
class TestDelivery:
    @pytest.fixture()
    def queued(self, enabled, watch_for, make_booking):
        start = timezone.now()
        watch = watch_for(start, start + 2 * H)
        booking = make_booking(starts_at=start - H, ends_at=start + 10 * M, status=BookingStatus.IN_PROGRESS)
        collect_slot_watch_notifications(now=start)
        return watch, booking

    def test_delivers_web_email_and_teams(self, queued, watcher):
        with (
            patch(
                "core.labs.features.bench_bookings.application.slot_watch_delivery.send_slot_email",
                return_value=DeliveryOutcome("sent", "accepted"),
            ) as email,
            patch(
                "core.labs.features.bench_bookings.application.slot_watch_delivery.send_slot_teams",
                return_value=DeliveryOutcome("sent", "accepted"),
            ) as teams,
            patch(
                "core.labs.features.bench_bookings.application.slot_watch_delivery.resolve_teams_recipient",
                return_value=object(),
            ),
            patch("core.labs.features.bench_bookings.application.slot_watch_delivery.publish_user_notification"),
        ):
            counts = deliver_slot_watch_notifications()
        assert counts["sent"] == 3
        assert email.call_args.kwargs["recipient"] == "watcher@example.invalid"
        teams.assert_called_once()
        web = Notification.objects.get(target_user=watcher)
        assert web.message.startswith("A bench you are watching frees up soon")
        assert set(BenchSlotNotification.objects.values_list("state", flat=True)) == {"sent"}

    def test_slot_taken_before_send_expires_without_sending(self, queued, make_booking):
        _, booking = queued
        make_booking(starts_at=booking.ends_at, ends_at=booking.ends_at + 3 * H)
        with patch("core.labs.features.bench_bookings.application.slot_watch_delivery.send_slot_email") as email:
            counts = deliver_slot_watch_notifications()
        email.assert_not_called()
        assert counts["expired"] == 3
        assert set(BenchSlotNotification.objects.values_list("outcome", flat=True)) == {"slot_taken"}

    def test_cancelled_watch_is_skipped(self, queued, watcher):
        watch, _ = queued
        cancel_slot_watch(actor=watcher, watch_id=watch.pk)
        counts = deliver_slot_watch_notifications()
        assert counts["skipped"] == 3
        assert not Notification.objects.exists()

    def test_email_failure_retries_independently(self, queued):
        with (
            patch(
                "core.labs.features.bench_bookings.application.slot_watch_delivery.send_slot_email",
                return_value=DeliveryOutcome("retry", "email_not_sent"),
            ),
            patch(
                "core.labs.features.bench_bookings.application.slot_watch_delivery.resolve_teams_recipient",
                return_value=None,
            ),
            patch("core.labs.features.bench_bookings.application.slot_watch_delivery.publish_user_notification"),
        ):
            counts = deliver_slot_watch_notifications()
        assert counts == counts | {"retry": 1, "sent": 1, "skipped": 1}
        email_row = BenchSlotNotification.objects.get(channel="email")
        assert email_row.state == "pending" and email_row.available_at > timezone.now()


@pytest.mark.django_db
def test_email_renders_slot_details(enabled):
    from django.core import mail

    from core.labs.features.bench_bookings.integrations.slot_watch_transport import send_slot_email

    now = timezone.now()
    snapshot = {
        "bench_name": "Bench 01",
        "bench_id": 1,
        "free_from": now.isoformat(),
        "free_until": (now + H).isoformat(),
        "range_start": now.isoformat(),
        "range_end": (now + 2 * H).isoformat(),
    }
    import uuid

    outcome = send_slot_email(
        recipient="watcher@example.invalid", kind="slot_freed", snapshot=snapshot, event_id=uuid.uuid4()
    )
    assert outcome.state == "sent"
    assert "Bench 01" in mail.outbox[0].body
    assert "not held for you" in mail.outbox[0].body


def test_enable_with_only_slot_watch_flag_enables_only_slot_schedules(settings):
    from unittest.mock import MagicMock

    from core.labs.management.commands import provision_booking_notification_schedules as schedules

    settings.BOOKING_NOTIFICATIONS_ENABLED = False
    settings.BOOKING_SLOT_WATCH_ENABLED = True
    with (
        patch.object(schedules.transaction, "atomic"),
        patch.object(schedules.IntervalSchedule.objects, "get_or_create", return_value=(MagicMock(), False)),
        patch.object(schedules.PeriodicTask.objects, "update_or_create") as tasks,
    ):
        command = schedules.Command()
        command.stdout = MagicMock()
        command.handle(enable=True)
    enabled_names = {c.kwargs["name"] for c in tasks.call_args_list if c.kwargs["defaults"]["enabled"]}
    assert enabled_names == {row[0] for row in schedules.SLOT_WATCH_SCHEDULES}


# --- booking follows -------------------------------------------------------------------------


@pytest.mark.django_db
class TestFollowBooking:
    @pytest.fixture()
    def follow(self, watcher):
        from core.labs.features.bench_bookings.application.slot_watches import follow_booking

        def _follow(booking):
            watch = follow_booking(actor=watcher, booking_id=booking.pk)
            BenchSlotWatch.objects.filter(pk=watch.pk).update(created=timezone.now() - H)
            watch.refresh_from_db()
            return watch

        return _follow

    def test_follow_is_idempotent_and_shows_on_calendar_scope(self, enabled, follow, make_booking, now):
        booking = make_booking(starts_at=now + H, ends_at=now + 2 * H)
        first = follow(booking)
        assert follow(booking).pk == first.pk
        assert first.target_booking_id == booking.pk and first.range_end == booking.ends_at

    def test_cannot_follow_own_or_ended_or_hidden_bookings(self, watcher, bench, make_booking, now):
        from core.labs.features.bench_bookings.application.slot_watches import follow_booking

        own = BenchBooking(bench=bench, starts_at=now + H, ends_at=now + 2 * H, booking_code="OWN-F-1")
        own.save(actor=watcher)
        with pytest.raises(SlotWatchInvalid):
            follow_booking(actor=watcher, booking_id=own.pk)
        cancelled = make_booking(starts_at=now + H, ends_at=now + 2 * H, status=BookingStatus.CANCELLED)
        with pytest.raises(BenchBooking.DoesNotExist):  # not on the shared calendar, not the watcher's: 404
            follow_booking(actor=watcher, booking_id=cancelled.pk)

    def test_one_alert_when_ending_soon_then_nothing_more(self, enabled, follow, make_booking, now):
        booking = make_booking(starts_at=now - H, ends_at=now + 10 * M, status=BookingStatus.IN_PROGRESS)
        watch = follow(booking)
        assert collect_slot_watch_notifications(now=now)["created"] == 3
        watch.refresh_from_db()
        assert watch.status == SlotWatchStatus.FULFILLED
        booking.status = BookingStatus.COMPLETED
        booking.completed_at = now
        booking.save(update_fields=("status", "completed_at", "modified"))
        assert collect_slot_watch_notifications(now=now + M)["created"] == 0
        assert set(BenchSlotNotification.objects.values_list("kind", flat=True)) == {"booking_ending_soon"}

    def test_natural_completion_alerts_when_ending_soon_was_missed(self, enabled, follow, make_booking, now):
        booking = make_booking(starts_at=now - 2 * H, ends_at=now - M, status=BookingStatus.IN_PROGRESS)
        BenchBooking.objects.filter(pk=booking.pk).update(ends_at=now + H)  # followable while running
        watch = follow(booking)
        BenchBooking.objects.filter(pk=booking.pk).update(
            ends_at=now - M, status=BookingStatus.COMPLETED, completed_at=now - M, modified=now
        )
        assert collect_slot_watch_notifications(now=now)["created"] == 3
        row = BenchSlotNotification.objects.filter(watch=watch).first()
        assert row.kind == "booking_released" and row.snapshot["is_follow"] is True

    def test_cancellation_alerts_with_free_until_next_booking(self, enabled, follow, make_booking, now):
        booking = make_booking(starts_at=now + H, ends_at=now + 3 * H)
        make_booking(starts_at=now + 3 * H, ends_at=now + 4 * H)
        follow(booking)
        _cancel(booking)
        collect_slot_watch_notifications(now=now)
        snapshot = BenchSlotNotification.objects.first().snapshot
        assert snapshot["free_until"] == (now + 3 * H).astimezone(dt_timezone.utc).isoformat()

    def test_pending_booking_rejection_alerts(self, enabled, follow, make_booking, now):
        booking = make_booking(starts_at=now + H, ends_at=now + 6 * H)
        BenchBooking.objects.filter(pk=booking.pk).update(approval_status=BookingApprovalStatus.PENDING)
        booking.refresh_from_db()
        follow(booking)
        booking.approval_status = BookingApprovalStatus.REJECTED
        booking.rejection_reason = "no"
        booking.save(update_fields=("approval_status", "rejection_reason", "modified"))
        assert collect_slot_watch_notifications(now=now)["created"] == 3

    def test_extension_moves_the_alert(self, enabled, follow, make_booking, now):
        booking = make_booking(starts_at=now - H, ends_at=now + H, status=BookingStatus.IN_PROGRESS)
        watch = follow(booking)
        BenchBooking.objects.filter(pk=booking.pk).update(ends_at=now + 3 * H)
        assert collect_slot_watch_notifications(now=now)["created"] == 0
        watch.refresh_from_db()
        assert watch.range_end == now + 3 * H and watch.status == SlotWatchStatus.ACTIVE
        assert collect_slot_watch_notifications(now=now + 3 * H - 10 * M)["created"] == 3

    def test_extended_after_queueing_expires_the_stale_alert(self, enabled, follow, make_booking, now):
        booking = make_booking(starts_at=now - H, ends_at=now + 10 * M, status=BookingStatus.IN_PROGRESS)
        follow(booking)
        collect_slot_watch_notifications(now=timezone.now())
        BenchBooking.objects.filter(pk=booking.pk).update(ends_at=now + 3 * H)
        counts = deliver_slot_watch_notifications()
        assert counts["expired"] == 3
        assert set(BenchSlotNotification.objects.values_list("outcome", flat=True)) == {"booking_changed"}

    def test_fulfilled_follow_still_delivers(self, enabled, follow, make_booking, watcher):
        now = timezone.now()
        booking = make_booking(starts_at=now - H, ends_at=now + 10 * M, status=BookingStatus.IN_PROGRESS)
        follow(booking)
        collect_slot_watch_notifications(now=now)
        with (
            patch(
                "core.labs.features.bench_bookings.application.slot_watch_delivery.send_slot_email",
                return_value=DeliveryOutcome("sent", "accepted"),
            ),
            patch(
                "core.labs.features.bench_bookings.application.slot_watch_delivery.resolve_teams_recipient",
                return_value=None,
            ),
            patch("core.labs.features.bench_bookings.application.slot_watch_delivery.publish_user_notification"),
        ):
            counts = deliver_slot_watch_notifications()
        assert counts["sent"] == 2 and counts["skipped"] == 1  # Teams identity not provisioned
        assert Notification.objects.get(target_user=watcher).message.startswith(
            "The booking you're following ends soon"
        )
