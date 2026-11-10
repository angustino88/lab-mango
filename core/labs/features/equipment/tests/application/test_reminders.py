"""Overdue reminders for loan slips (equipment booking revision 2, phase 3)."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.equipment.application import (
    LendEquipmentBatchInput,
    ReturnEquipmentInput,
    lend_equipment_batch,
    return_equipment,
)
from core.labs.features.equipment.application.reminders import collect_overdue_reminders, deliver_overdue_reminders
from core.labs.models import (
    ComputingEquipment,
    EquipmentCategory,
    EquipmentKind,
    EquipmentLoan,
    EquipmentLoanBatch,
    EquipmentLoanReminder,
)

User = get_user_model()


@pytest.fixture
def kind(db):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    return EquipmentKind.objects.create(category=category, name="Reminder PC")


def _lend(kind, count=1, prefix="RM", **borrower):
    items = [
        ComputingEquipment.objects.create(sku=f"{prefix}-{index}", name=f"Scope {index}", kind=kind)
        for index in range(count)
    ]
    borrower.setdefault("borrower_name", "Anna Tran")
    batch = lend_equipment_batch(
        LendEquipmentBatchInput(
            equipment_ids=tuple(item.pk for item in items),
            due_at=timezone.now() + timedelta(hours=1),
            purpose="EMC test week",
            **borrower,
        ),
        actor=None,
    )
    return batch, items


def _overdue_by(batch, delta):
    """Move the slip's loans so they were handed over earlier and are due ``delta`` ago."""
    due = timezone.now() - delta
    EquipmentLoan.objects.filter(batch=batch).update(handed_over_at=due - timedelta(days=2), due_at=due)


# Collect -------------------------------------------------------------------------------------


@pytest.mark.django_db
def test_slot_follows_the_schedule_and_each_slot_is_created_once(kind):
    batch, _ = _lend(kind, borrower_contact="anna@example.com")
    assert collect_overdue_reminders() == 0  # not due yet
    _overdue_by(batch, timedelta(minutes=5))
    assert collect_overdue_reminders() == 1
    assert collect_overdue_reminders() == 0  # re-run creates nothing
    _overdue_by(batch, timedelta(days=1, minutes=5))
    collect_overdue_reminders()
    _overdue_by(batch, timedelta(days=3, minutes=5))
    collect_overdue_reminders()
    assert list(batch.reminders.values_list("slot", flat=True)) == [0, 1, 3]  # missed slot 2 is not sent late


@pytest.mark.django_db
def test_reminders_stop_after_a_week(kind):
    batch, _ = _lend(kind, borrower_contact="anna@example.com")
    _overdue_by(batch, timedelta(days=7, hours=1))
    assert collect_overdue_reminders() == 1
    _overdue_by(batch, timedelta(days=8, hours=1))
    assert collect_overdue_reminders() == 0
    assert list(batch.reminders.values_list("slot", flat=True)) == [7]


@pytest.mark.django_db
def test_recipient_rules(kind):
    user = User.objects.create_user(username="rm-user", email="user@example.com")
    with_account, _ = _lend(
        kind, prefix="RM-A", borrower_id=user.pk, borrower_name="", borrower_contact="other@example.com"
    )
    with_email, _ = _lend(kind, prefix="RM-B", borrower_contact="anna@example.com")
    phone_only, _ = _lend(kind, prefix="RM-C", borrower_contact="+84 90 123 4567")
    for batch in (with_account, with_email, phone_only):
        _overdue_by(batch, timedelta(minutes=5))
    assert collect_overdue_reminders() == 2
    assert with_account.reminders.get().recipient_email == "user@example.com"
    assert with_email.reminders.get().recipient_email == "anna@example.com"
    assert not phone_only.reminders.exists()  # listed for the coordinator only


@pytest.mark.django_db
def test_one_reminder_per_slip_lists_every_overdue_item(kind):
    batch, items = _lend(kind, count=3, borrower_contact="anna@example.com")
    _overdue_by(batch, timedelta(minutes=5))
    collect_overdue_reminders()
    counts = deliver_overdue_reminders()
    assert counts["sent"] == 1 and len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["anna@example.com"] and "3 borrowed items" in message.subject
    assert all(item.sku in message.body for item in items) and "EMC test week" in message.body


# Deliver -------------------------------------------------------------------------------------


@pytest.mark.django_db
def test_returned_before_delivery_is_skipped(kind):
    batch, items = _lend(kind, borrower_contact="anna@example.com")
    _overdue_by(batch, timedelta(minutes=5))
    collect_overdue_reminders()
    return_equipment(ReturnEquipmentInput(equipment_id=items[0].pk), actor=None)
    assert deliver_overdue_reminders()["skipped"] == 1
    assert mail.outbox == [] and batch.reminders.get().outcome == "returned"


@pytest.mark.django_db
def test_send_failure_is_retried_later(kind):
    batch, _ = _lend(kind, borrower_contact="anna@example.com")
    _overdue_by(batch, timedelta(minutes=5))
    collect_overdue_reminders()
    with patch("core.labs.features.equipment.application.reminders.send_email", return_value=False):
        assert deliver_overdue_reminders()["retry"] == 1
    reminder = batch.reminders.get()
    assert reminder.state == "pending" and reminder.attempts == 1 and reminder.available_at > timezone.now()
    assert deliver_overdue_reminders()["claimed"] == 0  # waits for its backoff


@pytest.mark.django_db
def test_reminder_constraints(kind):
    batch, _ = _lend(kind, borrower_contact="anna@example.com")
    expires = timezone.now() + timedelta(days=1)
    EquipmentLoanReminder.objects.create(batch=batch, slot=0, recipient_email="a@example.com", expires_at=expires)
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        EquipmentLoanReminder.objects.create(batch=batch, slot=0, recipient_email="a@example.com", expires_at=expires)
    assert "equipment_loan_reminder_once_per_slot" in str(error.value)
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        EquipmentLoanReminder.objects.create(batch=batch, slot=8, recipient_email="a@example.com", expires_at=expires)
    assert "equipment_loan_reminder_slot_range" in str(error.value)
    assert EquipmentLoanBatch.objects.get(pk=batch.pk).reminders.count() == 1
