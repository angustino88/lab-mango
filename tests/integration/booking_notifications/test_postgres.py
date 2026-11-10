"""Real PostgreSQL proof obligations; skipped with dummy settings, never mocked concurrency."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event

import pytest
from django.conf import settings
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import override_settings

from core.labs.features.bench_bookings.application.notification_delivery import claim_one, complete_claim, reap_expired
from core.labs.features.bench_bookings.application.notification_intents import record_notification
from core.labs.features.bench_bookings.integrations.notification_transport import DeliveryOutcome
from core.labs.models import Bench, BenchBooking, BookingNotification
from core.users.models import User

pytestmark = [
    pytest.mark.skipif(settings.SETTINGS_MODULE != "tests.notification_postgres_settings",
                       reason="Disposable PostgreSQL is not enabled; no DB access."),
    pytest.mark.django_db(transaction=True),
]
NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
FLAGS = dict(BOOKING_NOTIFICATIONS_ENABLED=True, BOOKING_NOTIFICATIONS_EMAIL_ENABLED=True,
             BOOKING_NOTIFICATIONS_TEAMS_ENABLED=False, BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF=NOW - timedelta(days=1))


@pytest.fixture
def booking():
    owner = User.objects.create(username="synthetic-notification-owner", email="owner@example.invalid", is_active=True)
    bench = Bench.objects.create(sku="SYNTHETIC-NOTIFICATION-BENCH", name="Synthetic bench")
    return BenchBooking.objects.create(bench=bench, creator=owner, booking_code="SYNTHETIC-NOTIFICATION-BOOK",
                                       starts_at=NOW, ends_at=NOW + timedelta(hours=1),
                                       status="reserved", approval_status="approved")


def row_for(booking, **changes):
    values = dict(event_id=uuid.uuid4(), dedupe_key=uuid.uuid4().hex, booking=booking,
                  recipient=booking.creator, channel="email", kind="created", snapshot={},
                  created_at=NOW, available_at=NOW, expires_at=NOW + timedelta(hours=24))
    return BookingNotification.objects.create(**(values | changes))


@override_settings(**FLAGS)
def test_atomic_booking_mutation_and_outbox_rollback(booking):
    with pytest.raises(RuntimeError), transaction.atomic():
        booking.reason = "synthetic update"
        booking.save(update_fields=["reason"])
        assert record_notification(booking=booking, kind="updated", now=NOW) == 1
        assert BookingNotification.objects.count() == 1
        raise RuntimeError("synthetic rollback")
    booking.refresh_from_db()
    assert booking.reason != "synthetic update"
    assert BookingNotification.objects.count() == 0
    with transaction.atomic():
        assert record_notification(booking=booking, kind="created", now=NOW) == 1
    assert BookingNotification.objects.count() == 1


@override_settings(**FLAGS)
def test_concurrent_logical_event_unique_and_sent_not_resurrected(booking):
    barrier = Barrier(2)
    def insert():
        close_old_connections()
        try:
            item = BenchBooking.objects.get(pk=booking.pk)
            barrier.wait(timeout=5)
            return record_notification(booking=item, kind="start", logical_key=NOW.isoformat(), now=NOW)
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: insert(), range(2)))
    assert sorted(results) == [0, 1]
    row = BookingNotification.objects.get()
    row.state = "sent"
    row.save(update_fields=["state"])
    booking.ends_at += timedelta(hours=1)
    booking.save(update_fields=["ends_at"])
    assert record_notification(booking=booking, kind="start", logical_key=NOW.isoformat(), now=NOW) == 0
    row.refresh_from_db()
    assert row.state == "sent"


def test_skip_locked_and_concurrent_claims_are_distinct(booking):
    first = row_for(booking, expires_at=NOW + timedelta(minutes=1))
    second = row_for(booking, expires_at=NOW + timedelta(minutes=2))
    locked = Event()
    release = Event()
    def hold_lock():
        close_old_connections()
        try:
            with transaction.atomic():
                BookingNotification.objects.select_for_update().get(pk=first.pk)
                locked.set()
                assert release.wait(timeout=10)
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(hold_lock)
        try:
            assert locked.wait(timeout=5)
            assert claim_one(now=NOW).pk == second.pk
        finally:
            release.set()
        future.result(timeout=5)
    assert claim_one(now=NOW).pk == first.pk
    BookingNotification.objects.all().delete()
    row_for(booking)
    row_for(booking)
    barrier = Barrier(2)
    def claim():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            return claim_one(now=NOW).pk
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: claim(), range(2)))
    assert len(set(ids)) == 2


def test_reclaimed_token_fences_old_completion(booking):
    row_for(booking)
    old = claim_one(now=NOW)
    reclaimed_at = NOW + timedelta(seconds=121)
    new = claim_one(now=reclaimed_at)
    assert new.pk == old.pk and new.lease_token != old.lease_token
    assert not complete_claim(row=old, result=DeliveryOutcome("sent", "accepted"), now=reclaimed_at)
    assert complete_claim(row=new, result=DeliveryOutcome("sent", "accepted"), now=reclaimed_at)


def test_deadline_priority_survives_old_backlog_and_bounded_reaping(booking):
    for _ in range(30):
        row_for(booking, available_at=NOW - timedelta(hours=2))
    reminder = row_for(booking, kind="start", expires_at=NOW + timedelta(minutes=1))
    expired = row_for(booking, expires_at=NOW)
    active = row_for(booking, expires_at=NOW, state="leased", lease_token=uuid.uuid4(), lease_until=NOW + timedelta(seconds=1))
    assert claim_one(now=NOW).pk == reminder.pk
    assert reap_expired(now=NOW, limit=1) == 1
    expired.refresh_from_db()
    active.refresh_from_db()
    assert expired.state == "expired" and active.state == "leased"


@pytest.mark.parametrize("changes", [{"channel": "broadcast"}, {"kind": "unknown"}, {"state": "unknown"},
                                      {"state": "leased"}, {"lease_token": uuid.UUID(int=1)},
                                      {"attempts": -1}])
def test_actual_migration_constraints_reject_invalid_rows(booking, changes):
    with pytest.raises(IntegrityError), transaction.atomic():
        row_for(booking, **changes)


def test_migration_unique_constraint_and_introspection(booking):
    row = row_for(booking)
    with pytest.raises(IntegrityError), transaction.atomic():
        row_for(booking, dedupe_key=row.dedupe_key)
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, BookingNotification._meta.db_table)
    for name in ("booking_notice_channel", "booking_notice_kind", "booking_notice_state", "booking_notice_lease"):
        assert constraints[name]["check"]
