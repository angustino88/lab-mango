"""record_session_log: one completed session per agent push, safe to repeat."""

import importlib
import uuid
from datetime import timedelta
from threading import Barrier, Thread

import pytest
from django.db import connection
from django.utils import timezone

from core.labs.features.lab_sessions.public import (
    RecordSessionLogInput,
    SessionLogConflict,
    SessionLogEquipmentUnavailable,
    SessionLogInvalid,
    record_session_log,
)
from core.labs.models import LabSessionLog
from tests.factories import ComputingEquipmentFactory

NOW = timezone.now().replace(microsecond=0)
# The package re-exports the command under the module's name, so fetch the module itself.
record_module = importlib.import_module("core.labs.features.lab_sessions.application.record_session_log")


@pytest.fixture()
def computer(db):
    return ComputingEquipmentFactory()


def session(computer, **changes) -> RecordSessionLogInput:
    values = {
        "equipment_id": computer.pk,
        "agent_id": "agent-1",
        "event_id": uuid.UUID("5b0f6c1e-2a7d-4c9e-9a3b-0d6e4f1a2c77"),
        "login_time": NOW - timedelta(hours=3),
        "logout_time": NOW - timedelta(hours=1),
        "active_duration_seconds": 5400.0,
        "remote_user": "nguyen.an",
        "remote_ip": "10.20.4.17",
        "remote_host": "LT-NGUYENAN",
        "booking_code": "BK-7F3K9Q",
        "agent_version": "2.4.1",
    }
    values.update(changes)
    return RecordSessionLogInput(**values)


@pytest.mark.django_db
def test_stores_the_session_for_the_agents_computer(computer):
    record = record_session_log(session(computer), actor=None, now=NOW)

    assert record.created is True
    stored = LabSessionLog.objects.get(pk=record.id)
    assert stored.computing_equipment_id == computer.pk
    assert (stored.agent_id, stored.event_id) == ("agent-1", record.event_id)
    assert (stored.login_time, stored.logout_time) == (NOW - timedelta(hours=3), NOW - timedelta(hours=1))
    assert stored.active_duration_seconds == 5400.0
    assert (stored.remote_user, stored.remote_ip, stored.remote_host) == ("nguyen.an", "10.20.4.17", "LT-NGUYENAN")
    assert stored.booking_code == "BK-7F3K9Q"
    assert stored.agent_version == "2.4.1"
    assert stored.reported_at == NOW
    assert stored.remote_user_display_name is None and stored.host_name is None
    assert stored.creator_id is None


@pytest.mark.django_db
def test_replay_with_same_values_returns_stored_record(computer):
    first = record_session_log(session(computer), actor=None, now=NOW)
    again = record_session_log(session(computer, agent_version="2.4.2"), actor=None, now=NOW + timedelta(minutes=1))

    assert again.created is False
    assert again.id == first.id
    assert LabSessionLog.objects.count() == 1
    assert LabSessionLog.objects.get().agent_version == "2.4.1"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "changes",
    [
        {"logout_time": NOW - timedelta(minutes=59)},
        {"active_duration_seconds": 5399.0},
        {"remote_user": "someone.else"},
        {"remote_ip": "10.20.4.18"},
        {"remote_host": "OTHER-HOST"},
        {"booking_code": None},
    ],
)
def test_same_event_id_with_different_values_conflicts(computer, changes):
    record_session_log(session(computer), actor=None, now=NOW)

    with pytest.raises(SessionLogConflict):
        record_session_log(session(computer, **changes), actor=None, now=NOW)
    assert LabSessionLog.objects.count() == 1


@pytest.mark.django_db
def test_same_event_id_from_another_computer_is_a_separate_session(computer):
    other = ComputingEquipmentFactory()

    record_session_log(session(computer), actor=None, now=NOW)
    record = record_session_log(session(other), actor=None, now=NOW)

    assert record.created is True
    assert LabSessionLog.objects.count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize("code", [None, "", "   "])
def test_temp_login_has_no_booking_code(computer, code):
    record = record_session_log(session(computer, booking_code=code), actor=None, now=NOW)

    assert record.booking_code is None
    assert LabSessionLog.objects.get(pk=record.id).booking_code is None


@pytest.mark.django_db
def test_text_is_trimmed_and_ipv6_normalized(computer):
    record = record_session_log(
        session(computer, remote_user="  nguyen.an ", remote_host=" ", remote_ip="2001:0db8:0000::0001"),
        actor=None,
        now=NOW,
    )

    stored = LabSessionLog.objects.get(pk=record.id)
    assert (stored.remote_user, stored.remote_host, stored.remote_ip) == ("nguyen.an", None, "2001:db8::1")
    again = record_session_log(session(computer, remote_ip="2001:db8::1", remote_host=None), actor=None, now=NOW)
    assert again.created is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"logout_time": NOW + timedelta(minutes=5, seconds=1)}, "logout_time"),
        ({"login_time": NOW - timedelta(days=7, seconds=1)}, "login_time"),
        ({"logout_time": NOW - timedelta(hours=3)}, "logout_time"),
        ({"logout_time": NOW - timedelta(hours=4)}, "logout_time"),
        ({"active_duration_seconds": 7200.5}, "active_duration_seconds"),
        ({"active_duration_seconds": -1.0}, "active_duration_seconds"),
        ({"remote_user": "  "}, "remote_user"),
        ({"remote_ip": "not-an-ip"}, "remote_ip"),
    ],
)
def test_hard_limits(computer, changes, field):
    with pytest.raises(SessionLogInvalid) as error:
        record_session_log(session(computer, **changes), actor=None, now=NOW)

    assert error.value.details is not None and field in error.value.details
    assert not LabSessionLog.objects.exists()


@pytest.mark.django_db
def test_limits_are_inclusive(computer):
    record = record_session_log(
        session(
            computer,
            login_time=NOW - timedelta(days=7),
            logout_time=NOW + timedelta(minutes=5),
            active_duration_seconds=(timedelta(days=7, minutes=5)).total_seconds(),
        ),
        actor=None,
        now=NOW,
    )

    assert record.created is True


@pytest.mark.django_db
def test_deleted_computer_is_refused(computer):
    computer.deleted_at = NOW
    computer.save(update_fields=["deleted_at"])

    with pytest.raises(SessionLogEquipmentUnavailable):
        record_session_log(session(computer), actor=None, now=NOW)
    assert not LabSessionLog.objects.exists()


@pytest.mark.django_db
def test_insert_race_is_answered_from_the_winning_row(computer, monkeypatch):
    """The lookup misses a row a concurrent push just committed; the unique key decides."""
    winner = record_session_log(session(computer), actor=None, now=NOW)
    monkeypatch.setattr(record_module, "_find_stored", lambda key: None)

    replay = record_session_log(session(computer), actor=None, now=NOW)
    assert (replay.created, replay.id) == (False, winner.id)

    with pytest.raises(SessionLogConflict):
        record_session_log(session(computer, remote_user="someone.else"), actor=None, now=NOW)


@pytest.mark.django_db(transaction=True)
def test_concurrent_identical_pushes_store_one_row(computer):
    command = session(computer)
    barrier = Barrier(2)
    results, errors = [], []

    def push():
        try:
            barrier.wait(timeout=5)
            results.append(record_session_log(command, actor=None, now=NOW))
        except Exception as error:  # surfaced by the assertion below
            errors.append(error)
        finally:
            connection.close()

    threads = [Thread(target=push) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert sorted(result.created for result in results) == [False, True]
    assert len({result.id for result in results}) == 1
    assert LabSessionLog.objects.count() == 1
