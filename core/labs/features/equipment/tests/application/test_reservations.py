"""Equipment reservations: reserve, change, cancel, hand over, expire (booking revision 2, phase 2)."""

import threading
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.utils import timezone

from core.labs.features.equipment.application import (
    CancelReservationInput,
    ChangeConditionInput,
    ChangeLifecycleInput,
    ExtendLoanInput,
    HandOverEquipmentInput,
    HandOverReservationInput,
    PlaceEquipmentInput,
    ReserveEquipmentBatchInput,
    ReturnEquipmentInput,
    UpdateReservationInput,
    cancel_reservation,
    change_condition,
    change_lifecycle,
    expire_uncollected_reservations,
    extend_loan,
    hand_over_equipment,
    hand_over_reservation,
    place_equipment,
    reserve_equipment_batch,
    return_equipment,
    update_reservation,
)
from core.labs.features.equipment.exceptions import EquipmentNotAvailable, ReservationConflict
from core.labs.models import (
    Bench,
    EquipmentBooking,
    EquipmentCategory,
    EquipmentKind,
    EquipmentLoan,
)
from tests.factories import create_computing_equipment


@pytest.fixture
def kind(db):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    return EquipmentKind.objects.create(category=category, name="Reservation PC")


def _items(kind, count, prefix="RS"):
    return [
        create_computing_equipment(sku=f"{prefix}-{index}", name=f"Scope {index}", kind=kind)
        for index in range(count)
    ]


def _window(start_hours=24, length_hours=48):
    start = timezone.now() + timedelta(hours=start_hours)
    return start, start + timedelta(hours=length_hours)


def _reserve(items, window=None, **extra):
    starts_at, ends_at = window or _window()
    extra.setdefault("borrower_name", "Anna Tran (Supplier X)")
    return reserve_equipment_batch(
        ReserveEquipmentBatchInput(
            equipment_ids=tuple(item.pk for item in items), starts_at=starts_at, ends_at=ends_at, **extra
        ),
        actor=None,
    )


def _lines(batch, status=None):
    rows = EquipmentBooking.objects.filter(batch=batch).order_by("equipment_id")
    return list(rows.filter(status=status) if status else rows)


# Reserve -------------------------------------------------------------------------------------


@pytest.mark.django_db
def test_reserve_several_items_for_a_borrower_without_account(kind):
    items = _items(kind, 3)
    batch = _reserve(items, purpose="EMC test week")
    lines = _lines(batch)
    assert len(lines) == 3
    assert {(line.status, line.approval_status) for line in lines} == {("reserved", "approved")}
    assert lines[0].requester is None and lines[0].reason == "EMC test week"


@pytest.mark.django_db
def test_overlap_refuses_the_whole_reservation(kind):
    first, second = _items(kind, 2)
    window = _window()
    _reserve([first], window)
    with pytest.raises(ReservationConflict) as error:
        _reserve([second, first], window, borrower_name="Ben")
    assert list(error.value.details) == ["equipment_ids[1]"] and "reserved" in error.value.details["equipment_ids[1]"]
    assert not EquipmentBooking.objects.filter(equipment=second).exists()


@pytest.mark.django_db
def test_item_on_loan_can_be_reserved_after_its_due_time_only(kind):
    (item,) = _items(kind, 1)
    hand_over_equipment(
        HandOverEquipmentInput(equipment_id=item.pk, due_at=timezone.now() + timedelta(hours=10), borrower_name="X"),
        actor=None,
    )
    with pytest.raises(ReservationConflict) as error:
        _reserve([item], _window(start_hours=5))
    assert "on loan until" in error.value.details["equipment_ids[0]"]
    _reserve([item], _window(start_hours=24))  # owner decision R7


@pytest.mark.django_db
def test_reservation_gating(kind):
    benched, retired, repairing = _items(kind, 3)
    place_equipment(
        PlaceEquipmentInput(equipment_id=benched.pk, bench_id=Bench.objects.create(sku="RS-B", name="B").pk),
        actor=None,
    )
    change_lifecycle(ChangeLifecycleInput(equipment_id=retired.pk, lifecycle_state="retired"), actor=None)
    change_condition(ChangeConditionInput(equipment_id=repairing.pk, condition="in_maintenance"), actor=None)
    with pytest.raises(ReservationConflict) as error:
        _reserve([benched, retired])
    assert "placed on a bench" in error.value.details["equipment_ids[0]"]
    assert "lifecycle state is retired" in error.value.details["equipment_ids[1]"]
    _reserve([repairing])  # condition is checked at hand-over, not at reservation


@pytest.mark.django_db
def test_window_validation(kind):
    (item,) = _items(kind, 1)
    start = timezone.now() + timedelta(hours=2)
    with pytest.raises(ValidationError):
        _reserve([item], (start, start))
    with pytest.raises(ValidationError):
        _reserve([item], (start - timedelta(days=2), start - timedelta(days=1)))


# Change and cancel ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_moves_window_adds_and_removes_items(kind):
    first, second, third = _items(kind, 3)
    batch = _reserve([first, second])
    new_start, new_end = _window(start_hours=72)
    update_reservation(
        UpdateReservationInput(
            batch_id=batch.pk,
            starts_at=new_start,
            ends_at=new_end,
            add_equipment_ids=(third.pk,),
            remove_equipment_ids=(second.pk,),
        ),
        actor=None,
    )
    reserved = _lines(batch, "reserved")
    assert [line.equipment_id for line in reserved] == [first.pk, third.pk]
    assert {(line.starts_at, line.ends_at) for line in reserved} == {(new_start, new_end)}
    assert _lines(batch, "cancelled")[0].equipment_id == second.pk


@pytest.mark.django_db
def test_update_into_another_reservation_is_refused(kind):
    (item,) = _items(kind, 1)
    _reserve([item], _window(start_hours=100), borrower_name="Other")
    batch = _reserve([item], _window(start_hours=24))
    start, end = _window(start_hours=90)
    with pytest.raises(ReservationConflict):
        update_reservation(UpdateReservationInput(batch_id=batch.pk, starts_at=start, ends_at=end), actor=None)


@pytest.mark.django_db
def test_cancel_all_or_some_with_reason(kind):
    first, second = _items(kind, 2)
    batch = _reserve([first, second])
    with pytest.raises(ValidationError):
        cancel_reservation(CancelReservationInput(batch_id=batch.pk, reason=" "), actor=None)
    cancel_reservation(
        CancelReservationInput(batch_id=batch.pk, reason="Project moved", equipment_ids=(first.pk,)), actor=None
    )
    assert [line.equipment_id for line in _lines(batch, "reserved")] == [second.pk]
    cancel_reservation(CancelReservationInput(batch_id=batch.pk, reason="Project cancelled"), actor=None)
    cancel_reservation(CancelReservationInput(batch_id=batch.pk, reason="Repeat"), actor=None)  # no-op
    assert {line.cancellation_reason for line in _lines(batch)} == {"Project moved", "Project cancelled"}


# Hand over, return, extend, lost --------------------------------------------------------------


@pytest.mark.django_db
def test_hand_over_partially_then_the_rest_and_return_completes(kind):
    first, second = _items(kind, 2)
    batch = _reserve([first, second], _window(start_hours=0.01))
    hand_over_reservation(
        HandOverReservationInput(
            batch_id=batch.pk, equipment_ids=(first.pk,), conditions_out=((first.pk, "Scratch"),)
        ),
        actor=None,
    )
    loan = EquipmentLoan.objects.get(equipment=first, returned_at__isnull=True)
    line = EquipmentBooking.objects.get(batch=batch, equipment=first)
    assert line.status == "in_progress" and loan.booking_id == line.pk and loan.due_at == line.ends_at
    assert loan.batch_id == batch.pk and loan.condition_out == "Scratch"
    hand_over_reservation(HandOverReservationInput(batch_id=batch.pk), actor=None)  # the rest; first is left as is
    assert EquipmentLoan.objects.filter(batch=batch, returned_at__isnull=True).count() == 2
    return_equipment(ReturnEquipmentInput(equipment_id=first.pk), actor=None)
    line.refresh_from_db()
    assert line.status == "completed"


@pytest.mark.django_db
def test_hand_over_is_all_or_nothing(kind):
    first, second = _items(kind, 2)
    batch = _reserve([first, second], _window(start_hours=0.01))
    change_condition(ChangeConditionInput(equipment_id=second.pk, condition="out_of_service"), actor=None)
    with pytest.raises(EquipmentNotAvailable) as error:
        hand_over_reservation(HandOverReservationInput(batch_id=batch.pk), actor=None)
    assert list(error.value.details) == ["equipment_ids[1]"]
    assert not EquipmentLoan.objects.filter(batch=batch).exists()


@pytest.mark.django_db
def test_extending_a_booked_loan_moves_the_booking_and_respects_the_next_reservation(kind):
    (item,) = _items(kind, 1)
    batch = _reserve([item], _window(start_hours=0.01, length_hours=24))
    hand_over_reservation(HandOverReservationInput(batch_id=batch.pk), actor=None)
    _reserve([item], _window(start_hours=60), borrower_name="Next borrower")
    later = timezone.now() + timedelta(hours=40)
    extend_loan(ExtendLoanInput(equipment_id=item.pk, due_at=later), actor=None)
    assert EquipmentBooking.objects.get(batch=batch).ends_at == later
    with pytest.raises(ReservationConflict):
        extend_loan(ExtendLoanInput(equipment_id=item.pk, due_at=timezone.now() + timedelta(hours=70)), actor=None)


@pytest.mark.django_db
def test_marking_lost_cancels_the_in_progress_booking(kind):
    (item,) = _items(kind, 1)
    batch = _reserve([item], _window(start_hours=0.01))
    hand_over_reservation(HandOverReservationInput(batch_id=batch.pk), actor=None)
    change_lifecycle(
        ChangeLifecycleInput(equipment_id=item.pk, lifecycle_state="lost", reason="Not returned"), actor=None
    )
    line = EquipmentBooking.objects.get(batch=batch)
    assert line.status == "cancelled" and line.cancellation_reason == "Not returned"
    assert EquipmentLoan.objects.get(batch=batch).close_reason == "lost"


# Expiry --------------------------------------------------------------------------------------


@pytest.mark.django_db
def test_uncollected_reservation_expires_after_its_start_day(kind):
    stale, today, collected = _items(kind, 3)
    old = _reserve([stale], _window(start_hours=-30, length_hours=60))
    current = _reserve([today], _window(start_hours=0.01))
    taken = _reserve([collected], _window(start_hours=-30, length_hours=60))
    hand_over_reservation(HandOverReservationInput(batch_id=taken.pk), actor=None)
    assert expire_uncollected_reservations() == 1
    assert _lines(old)[0].status == "expired"
    assert _lines(current)[0].status == "reserved" and _lines(taken)[0].status == "in_progress"
    assert expire_uncollected_reservations() == 0


# Concurrency (PostgreSQL) --------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_two_reservations_of_one_item_and_window_one_wins(kind):
    (item,) = _items(kind, 1, prefix="RS-C")
    window = _window()
    barrier = threading.Barrier(2)
    outcomes = []

    def reserve(name):
        try:
            barrier.wait()
            reserve_equipment_batch(
                ReserveEquipmentBatchInput(
                    equipment_ids=(item.pk,), starts_at=window[0], ends_at=window[1], borrower_name=name
                ),
                actor=None,
            )
            outcomes.append("ok")
        except ReservationConflict:
            outcomes.append("conflict")
        finally:
            close_old_connections()

    threads = [threading.Thread(target=reserve, args=(name,)) for name in ("A", "B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["conflict", "ok"]
    assert EquipmentBooking.objects.filter(equipment=item, status="reserved").count() == 1
