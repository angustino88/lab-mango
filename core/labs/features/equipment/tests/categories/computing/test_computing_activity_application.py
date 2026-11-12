"""Application tests for the computing equipment live activity commands."""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.equipment.application import CreateEquipmentInput, create_equipment
from core.labs.features.equipment.categories.computing.application import (
    SyncComputingActivityInput,
    ensure_computing_activity,
    mark_stale_computing_activities_offline,
    sync_computing_activity,
)
from core.labs.models import ComputingActivity, ComputingActivityStatus, Equipment
from core.labs.models.resource.equipment.reference_data import EquipmentCategory, EquipmentKind
from tests.factories import create_computing_equipment


@pytest.fixture()
def computing(db):
    category = EquipmentCategory.objects.create(name="Computing", definition="Computing equipment", monitored=True)
    kind = EquipmentKind.objects.create(category=category, name="Computer")
    return create_computing_equipment(sku="COMP-ACT-1", name="Host 1", kind=kind)


def _sync(target, /, **fields):
    return sync_computing_activity(
        SyncComputingActivityInput(computing_id=target.pk, fields=tuple(fields.items())),
        actor=None,
    )


def test_create_computing_equipment_creates_offline_activity(computing):
    category = computing.kind.category
    created = create_equipment(
        CreateEquipmentInput(fields=(("kind", computing.kind), ("sku", "COMP-NEW"), ("name", "New host"))),
        actor=None,
    )

    assert category.name == "Computing"
    assert created.activity.status == ComputingActivityStatus.OFFLINE


def test_ensure_activity_is_idempotent(computing):
    first = ensure_computing_activity(computing)
    second = ensure_computing_activity(computing)

    assert first.pk == second.pk
    assert ComputingActivity.objects.filter(computing=computing).count() == 1


def test_sync_creates_missing_row_and_sets_fields(computing):
    activity = _sync(computing, status="active", remote_user="alice", booking_code="BK-1", remote_ip="10.0.0.5")

    assert activity.status == ComputingActivityStatus.ACTIVE
    assert activity.remote_user == "alice"
    assert activity.booking_code == "BK-1"
    assert activity.remote_ip == "10.0.0.5"
    assert activity.offline_at is None


def test_going_offline_stamps_offline_at_and_coming_back_clears_it(computing):
    _sync(computing, status="free")
    offline = _sync(computing, status="offline")
    assert offline.offline_at is not None

    back = _sync(computing, status="free")
    assert back.offline_at is None


def test_offline_activity_requires_offline_at_in_database(computing):
    with pytest.raises(IntegrityError), transaction.atomic():
        ComputingActivity.objects.create(computing=computing, status=ComputingActivityStatus.OFFLINE)


def test_offline_activity_with_timestamp_is_valid(computing):
    activity = ComputingActivity.objects.create(
        computing=computing,
        status=ComputingActivityStatus.OFFLINE,
        offline_at=timezone.now(),
    )

    assert activity.pk is not None


def test_default_offline_activity_may_have_no_offline_timestamp(computing):
    activity = ensure_computing_activity(computing)

    assert activity.status == ComputingActivityStatus.OFFLINE
    assert activity.offline_at is not None


def test_inactive_transition_manages_timestamp_and_reminders(computing):
    _sync(computing, status="active")
    inactive = _sync(computing, status="inactive")
    assert inactive.inactive_at is not None
    ComputingActivity.objects.filter(pk=inactive.pk).update(inactive_reminder_count=3)

    active = _sync(computing, status="active")

    assert active.inactive_at is None
    assert active.inactive_reminder_count == 0


def test_inactive_activity_requires_inactive_at_in_database(computing):
    with pytest.raises(IntegrityError), transaction.atomic():
        ComputingActivity.objects.create(computing=computing, status=ComputingActivityStatus.INACTIVE)


def test_inactive_activity_with_timestamp_is_valid(computing):
    from django.utils import timezone

    activity = ComputingActivity.objects.create(
        computing=computing,
        status=ComputingActivityStatus.INACTIVE,
        inactive_at=timezone.now(),
    )

    assert activity.pk is not None


def test_non_inactive_activity_may_have_no_inactive_at(computing):
    activity = ComputingActivity.objects.create(computing=computing, status=ComputingActivityStatus.FREE)

    assert activity.inactive_at is None


def test_database_rejects_changing_status_to_inactive_without_timestamp(computing):
    activity = ComputingActivity.objects.create(computing=computing, status=ComputingActivityStatus.FREE)

    with pytest.raises(IntegrityError), transaction.atomic():
        ComputingActivity.objects.filter(pk=activity.pk).update(status=ComputingActivityStatus.INACTIVE)


def test_same_status_does_not_touch_timestamps(computing):
    first = _sync(computing, status="inactive")
    stamp = first.inactive_at
    reminder_count = 4
    ComputingActivity.objects.filter(pk=first.pk).update(inactive_reminder_count=reminder_count)

    second = _sync(computing, status="inactive", remote_user="bob")

    assert second.inactive_at == stamp
    assert second.inactive_reminder_count == reminder_count
    assert second.last_agent_report_at is not None


def test_coordinator_update_does_not_refresh_agent_heartbeat(computing):
    original_heartbeat = timezone.now() - timedelta(minutes=5)
    activity = ComputingActivity.objects.create(
        computing=computing,
        status=ComputingActivityStatus.FREE,
        last_agent_report_at=original_heartbeat,
    )
    sync_computing_activity(
        SyncComputingActivityInput(computing_id=computing.pk, fields=(("remote_user", "coordinator"),)),
        actor=object(),
    )
    activity.refresh_from_db()

    assert activity.last_agent_report_at == original_heartbeat


def test_agent_report_refreshes_heartbeat_without_status_change(computing):
    first = _sync(computing, status="inactive")
    inactive_at = first.inactive_at

    second = _sync(computing, status="inactive")

    assert second.last_agent_report_at >= first.last_agent_report_at
    assert second.inactive_at == inactive_at


def test_stale_agent_activity_becomes_offline_only_after_strict_timeout(computing):
    now = timezone.now()
    exactly_ten_minutes = ComputingActivity.objects.create(
        computing=computing,
        status=ComputingActivityStatus.ACTIVE,
        last_agent_report_at=now - timedelta(minutes=10),
    )
    assert mark_stale_computing_activities_offline(now=now) == 0
    exactly_ten_minutes.refresh_from_db()
    assert exactly_ten_minutes.status == ComputingActivityStatus.ACTIVE

    stale = ComputingActivity.objects.create(
        computing=create_computing_equipment(sku="COMP-ACT-STALE", name="Stale host", kind=computing.kind),
        status=ComputingActivityStatus.ACTIVE,
        last_agent_report_at=now - timedelta(minutes=10, microseconds=1),
    )

    assert mark_stale_computing_activities_offline(now=now) == 1
    stale.refresh_from_db()
    assert stale.status == ComputingActivityStatus.OFFLINE
    assert stale.offline_at == now


@pytest.mark.parametrize("status", ComputingActivityStatus.values)
def test_stale_sweep_offlines_every_stale_status_except_offline(computing, status):
    now = timezone.now()
    target = computing
    if status != ComputingActivityStatus.FREE:
        target = create_computing_equipment(sku=f"COMP-{status.upper()}", name=status, kind=computing.kind)
    activity = ComputingActivity.objects.create(
        computing=target,
        status=status,
        offline_at=now - timedelta(hours=1) if status == ComputingActivityStatus.OFFLINE else None,
        inactive_at=now - timedelta(minutes=1) if status == ComputingActivityStatus.INACTIVE else None,
        last_agent_report_at=now - timedelta(minutes=11),
    )

    changed = mark_stale_computing_activities_offline(now=now)

    activity.refresh_from_db()
    if status == ComputingActivityStatus.OFFLINE:
        assert changed == 0
        assert activity.offline_at == now - timedelta(hours=1)
    else:
        assert changed == 1
        assert activity.status == ComputingActivityStatus.OFFLINE
        assert activity.offline_at == now


def test_stale_agent_activity_sweep_ignores_null_heartbeat_and_offline_rows(computing):
    now = timezone.now()
    coordinator_only = ComputingActivity.objects.create(
        computing=computing,
        status=ComputingActivityStatus.ACTIVE,
        last_agent_report_at=None,
    )
    computing_two = create_computing_equipment(sku="COMP-ACT-2", name="Host 2", kind=computing.kind)
    already_offline = ComputingActivity.objects.create(
        computing=computing_two,
        status=ComputingActivityStatus.OFFLINE,
        offline_at=now - timedelta(hours=1),
        last_agent_report_at=now - timedelta(hours=1),
    )

    assert mark_stale_computing_activities_offline(now=now) == 0
    coordinator_only.refresh_from_db()
    already_offline.refresh_from_db()
    assert coordinator_only.status == ComputingActivityStatus.ACTIVE
    assert already_offline.offline_at == now - timedelta(hours=1)


def test_stale_sweep_does_not_offline_a_row_refreshed_before_lock_is_acquired(computing, monkeypatch):
    now = timezone.now()
    activity = ComputingActivity.objects.create(
        computing=computing,
        status=ComputingActivityStatus.ACTIVE,
        last_agent_report_at=now - timedelta(minutes=11),
    )
    original_filter = ComputingActivity.objects.__class__.filter
    refreshed = False

    def refresh_before_stale_candidates_are_evaluated(queryset, *args, **kwargs):
        nonlocal refreshed
        stale_queryset = original_filter(queryset, *args, **kwargs)
        if not refreshed and "last_agent_report_at__lt" in kwargs:
            refreshed = True
            ComputingActivity.objects.filter(pk=activity.pk).update(last_agent_report_at=now)
        return stale_queryset

    monkeypatch.setattr(ComputingActivity.objects.__class__, "filter", refresh_before_stale_candidates_are_evaluated)

    assert mark_stale_computing_activities_offline(now=now) == 0
    activity.refresh_from_db()
    assert refreshed
    assert activity.status == ComputingActivityStatus.ACTIVE
    assert activity.last_agent_report_at == now


def test_partial_sync_preserves_unspecified_fields(computing):
    _sync(computing, status="active", remote_user="alice")

    updated = _sync(computing, booking_code="BK-9")

    assert updated.status == ComputingActivityStatus.ACTIVE
    assert updated.remote_user == "alice"
    assert updated.booking_code == "BK-9"


@pytest.mark.parametrize("field", ["offline_at", "inactive_at", "inactive_reminder_count", "computing", "id"])
def test_server_managed_fields_are_rejected(computing, field):
    with pytest.raises(ValidationError) as error:
        _sync(computing, **{field: 1})

    assert field in error.value.message_dict


def test_invalid_status_is_rejected(computing):
    with pytest.raises(ValidationError) as error:
        _sync(computing, status="exploded")

    assert "status" in error.value.message_dict


def test_missing_or_deleted_computer_raises_does_not_exist(computing):
    from django.utils import timezone

    with pytest.raises(Equipment.DoesNotExist):
        sync_computing_activity(SyncComputingActivityInput(computing_id=0, fields=(("status", "free"),)))

    Equipment.objects.filter(pk=computing.pk).update(deleted_at=timezone.now())
    with pytest.raises(Equipment.DoesNotExist):
        _sync(computing, status="free")


def test_status_change_notifies_after_commit(computing, monkeypatch, django_capture_on_commit_callbacks):
    published = []
    monkeypatch.setattr(
        "core.websocket.publish_service.publish_computing_activity_update",
        lambda computing_id, data: published.append((computing_id, data)),
    )
    monkeypatch.setattr("core.websocket.publish_service.publish_monitoring_update", lambda *a, **k: None)
    monkeypatch.setattr("core.websocket.publish_service.publish_dashboard_status_update", lambda *a, **k: None)
    _sync(computing, status="free")

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        _sync(computing, status="active")

    assert len(callbacks) == 1
    assert published == [
        (computing.pk, {"computer_id": computing.pk, "status": "active", "previous_status": "free", "bench_id": None})
    ]


def test_repeating_offline_status_does_not_emit_another_status_notification(
    computing, monkeypatch, django_capture_on_commit_callbacks
):
    published = []
    monkeypatch.setattr(
        "core.websocket.publish_service.publish_computing_activity_update",
        lambda computing_id, data: published.append((computing_id, data)),
    )
    monkeypatch.setattr("core.websocket.publish_service.publish_monitoring_update", lambda *a, **k: None)
    monkeypatch.setattr("core.websocket.publish_service.publish_dashboard_status_update", lambda *a, **k: None)
    with django_capture_on_commit_callbacks(execute=True):
        first = _sync(computing, status="active")
        offline = _sync(computing, status="offline")
    original_offline_at = offline.offline_at

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        repeated = _sync(computing, status="offline")

    assert first.status == ComputingActivityStatus.ACTIVE
    assert repeated.offline_at == original_offline_at
    assert callbacks == []
    assert [event[1]["status"] for event in published] == ["active", "offline"]
