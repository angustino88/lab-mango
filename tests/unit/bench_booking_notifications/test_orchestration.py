"""Exercise use-case hooks, collectors, beat provisioning and migration state offline."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.db.migrations.state import ModelState
from django.test import override_settings

from core.labs.features.bench_bookings.application import create_booking as create_module
from core.labs.features.bench_bookings.application import notification_collection as collection
from core.labs.features.bench_bookings.application import notification_delivery as delivery
from core.labs.features.bench_bookings.application import update_booking as update_module
from core.labs.features.bench_bookings.integrations.notification_transport import DeliveryOutcome
from core.labs.features.bench_bookings.tasks import (
    collect_booking_notifications_task,
    deliver_booking_notifications_task,
)
from core.labs.features.equipment.contracts import InactiveEquipmentSnapshot
from core.labs.features.equipment.queries.inactivity_notifications import inactive_equipment_candidates
from core.labs.management.commands import provision_booking_notification_schedules as schedules
from core.labs.models import BookingNotification

from .test_notifications import FLAGS, NOW, TEAMS_RECIPIENT, booking, notice


def test_create_records_inside_existing_transaction():
    item = booking()
    item.save = MagicMock()
    data = create_module.CreateBenchBookingInput(bench_id=3, starts_at=NOW, ends_at=NOW + timedelta(hours=1))
    with (
        patch.object(create_module, "policies"),
        patch.object(create_module, "lock_benches", return_value={3: MagicMock()}),
        patch.object(create_module, "conflicting_bench_bookings"),
        patch.object(create_module, "bench_parent_blocker", return_value=None),
        patch.object(create_module, "bench_downtime_blocker", return_value=None),
        patch.object(create_module, "generate_booking_code"),
        patch.object(create_module, "BenchBooking", return_value=item),
        patch.object(create_module.transaction, "atomic") as atomic,
        patch.object(create_module, "record_notification") as record,
    ):
        transaction_open = []
        atomic.return_value.__enter__.side_effect = lambda: transaction_open.append(True)
        atomic.return_value.__exit__.side_effect = lambda *args: transaction_open.pop() and False
        record.side_effect = lambda **kwargs: len(transaction_open) == 1 or (_ for _ in ()).throw(AssertionError())
        assert create_module.create_bench_booking(actor=MagicMock(), data=data) is item
        record.assert_called_once_with(booking=item, kind="created")
        assert not transaction_open


def test_update_hook_noop_and_material_inside_transaction():
    for fields, expected in (
        ({}, 0),
        ({"reason": "synthetic"}, 0),
        ({"reason": "original synthetic reason"}, 0),
        ({"ends_at": NOW + timedelta(hours=2)}, 1),
    ):
        item = booking()
        item.save = MagicMock()
        data = update_module.UpdateBenchBookingInput(booking_id=7, fields=fields)
        with (
            patch.object(update_module, "policies"),
            patch.object(update_module, "_ensure_can_modify"),
            patch.object(update_module, "lock_benches", return_value={3: MagicMock()}),
            patch.object(update_module, "conflicting_bench_bookings"),
            patch.object(update_module, "bench_parent_blocker", return_value=None),
            patch.object(update_module, "bench_downtime_blocker", return_value=None),
            patch.object(update_module.BenchBooking.objects, "values_list") as ids,
            patch.object(update_module.BenchBooking.objects, "select_for_update") as locked,
            patch.object(update_module.transaction, "atomic") as atomic,
            patch.object(update_module, "record_notification") as record,
        ):
            ids.return_value.get.return_value = 3
            locked.return_value.get.return_value = item
            inside = []
            atomic.return_value.__enter__.side_effect = lambda: inside.append(True)
            atomic.return_value.__exit__.side_effect = lambda *args: inside.pop() and False

            def check_transaction(**kwargs):
                assert inside

            record.side_effect = check_transaction
            assert update_module.update_bench_booking(actor=MagicMock(), data=data) is item
            assert record.call_count == expected
            assert not inside


@override_settings(**FLAGS)
def test_collection_revalidates_and_emits_episode_key():
    candidate = InactiveEquipmentSnapshot(
        4, 3, "BOOK-SYNTHETIC", NOW - timedelta(minutes=61), NOW - timedelta(hours=2)
    )
    item = booking()
    with (
        patch.object(collection.transaction, "atomic"),
        patch.object(collection.BenchBooking.objects, "filter") as query,
        patch.object(collection.BenchBooking.objects, "select_for_update") as locked,
        patch.object(
            collection, "inactive_equipment_candidates", side_effect=[[candidate], [candidate]]
        ) as projections,
        patch.object(collection, "record_notification", return_value=2) as record,
    ):
        query.return_value.order_by.return_value.values_list.return_value.__getitem__.return_value = []
        locked.return_value.filter.return_value.first.return_value = item
        result = collection.collect_notifications(now=NOW)
        assert result["created"] == 2
        assert record.call_args.kwargs["kind"] == "inactive"
        assert record.call_args.kwargs["logical_key"] == f"4:{candidate.inactive_at.isoformat()}"
        assert projections.call_count == 2


@override_settings(**FLAGS)
def test_delivery_partial_channel_failure_and_no_lock_across_io():
    rows = [notice(kind="created", channel="email"), notice(kind="created", channel="teams")]
    with (
        patch.object(delivery.timezone, "now", return_value=NOW),
        patch.object(delivery, "claim_one", side_effect=[*rows, None]),
        patch.object(delivery, "reap_expired", return_value=0),
        patch.object(delivery, "owns_lease", return_value=True),
        patch.object(delivery, "resolve_teams_recipient", return_value=TEAMS_RECIPIENT),
        patch.object(delivery.BookingNotification.objects, "select_related") as reads,
        patch.object(
            delivery,
            "deliver",
            side_effect=[DeliveryOutcome("sent", "accepted"), DeliveryOutcome("retry", "http_transient")],
        ),
        patch.object(delivery, "complete_claim", return_value=True),
        patch.object(delivery.transaction, "atomic") as atomic,
    ):
        reads.return_value.get.side_effect = rows
        result = delivery.deliver_notifications()
        assert result["sent"] == 1 and result["retry"] == 1
        # Claims own their separate short transaction; delivery itself never opens one.
        atomic.assert_not_called()


@override_settings(**FLAGS)
def test_delivery_does_not_adopt_reclaimed_token():
    original = notice(kind="created")
    replacement = notice(pk=original.pk, kind="created")
    with (
        patch.object(delivery.timezone, "now", return_value=NOW),
        patch.object(delivery, "claim_one", side_effect=[original, None]),
        patch.object(delivery, "reap_expired", return_value=0),
        patch.object(delivery.BookingNotification.objects, "select_related") as reads,
        patch.object(delivery, "deliver") as send,
    ):
        reads.return_value.get.return_value = replacement
        assert delivery.deliver_notifications()["fenced"] == 1
        send.assert_not_called()


def test_tasks_registered_and_keyset_continuation():
    assert collect_booking_notifications_task.name == "labs.bench_bookings.collect_notifications"
    assert deliver_booking_notifications_task.name == "labs.bench_bookings.deliver_notifications"
    assert deliver_booking_notifications_task.time_limit < delivery.LEASE_SECONDS
    with (
        patch.object(
            collection,
            "collect_notifications",
            return_value={"created": 0, "booking_cursor": -1, "equipment_cursor": 101},
        ),
        patch.object(collect_booking_notifications_task, "apply_async") as enqueue,
    ):
        collect_booking_notifications_task.run()
        assert enqueue.call_args.kwargs["args"] == (-1, 101, 1)
        assert enqueue.call_args.kwargs["queue"] == "booking_notifications"


def test_beat_provision_disabled_and_idempotent_keys():
    with (
        patch.object(schedules.transaction, "atomic"),
        patch.object(schedules.IntervalSchedule.objects, "get_or_create") as intervals,
        patch.object(schedules.PeriodicTask.objects, "update_or_create") as tasks,
    ):
        intervals.return_value = (MagicMock(), False)
        command = schedules.Command()
        command.stdout = MagicMock()
        command.handle(enable=False)
        command.handle(enable=False)
        assert tasks.call_count == 4
        assert all(not call.kwargs["defaults"]["enabled"] for call in tasks.call_args_list)
        assert [call.kwargs["name"] for call in tasks.call_args_list[:2]] == [row[0] for row in schedules.SCHEDULES]


def test_migration_graph_matches_current_booking_notification_model_without_connection():
    # Compare the model against the state projected from the whole migration graph.
    from django.db.migrations.loader import MigrationLoader

    projected = MigrationLoader(None, ignore_no_migrations=True).project_state()
    expected = ModelState.from_model(BookingNotification)
    actual = projected.models[("labs", "bookingnotification")]

    # Compare by meaning: AddField/AddConstraint append, so declaration order differs harmlessly.
    def fields(state):
        return {name: field.deconstruct()[1:] for name, field in state.fields.items()}

    def constraints(state):
        return {constraint.name: constraint.deconstruct() for constraint in state.options.get("constraints", [])}

    def other_options(state):
        return {key: value for key, value in state.options.items() if key != "constraints"}

    assert fields(expected) == fields(actual)
    assert constraints(expected) == constraints(actual)
    assert other_options(expected) == other_options(actual)


def test_real_orm_projection_builds_without_database_access():
    from django.db.models import QuerySet

    with patch.object(QuerySet, "__iter__", return_value=iter(())):
        assert inactive_equipment_candidates(now=NOW, equipment_id=4) == []
