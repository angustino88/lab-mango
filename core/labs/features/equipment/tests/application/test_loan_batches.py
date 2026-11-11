"""Loan slips: several items, borrowers without accounts, purpose (equipment booking revision 2)."""

import threading
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.utils import timezone

from core.labs.features.equipment.application import (
    ExtendLoansInput,
    HandOverEquipmentInput,
    LendEquipmentBatchInput,
    PlaceEquipmentInput,
    ReturnEquipmentBatchInput,
    ReturnEquipmentInput,
    extend_loans,
    hand_over_equipment,
    lend_equipment_batch,
    place_equipment,
    return_equipment_batch,
)
from core.labs.features.equipment.exceptions import (
    EquipmentNotAvailable,
    EquipmentNotOnLoan,
    LoanIdempotencyKeyReuse,
)
from core.labs.models import (
    Bench,
    EquipmentBooking,
    EquipmentCategory,
    EquipmentKind,
    EquipmentLoan,
    EquipmentLoanBatch,
    EquipmentPlacement,
    Room,
    Station,
)
from tests.factories import create_computing_equipment

User = get_user_model()


@pytest.fixture
def kind(db):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    return EquipmentKind.objects.create(category=category, name="Batch PC")


def _items(kind, count, prefix="LB"):
    return [
        create_computing_equipment(sku=f"{prefix}-{index}", name=f"Item {index}", kind=kind)
        for index in range(count)
    ]


def _due(hours=48):
    return timezone.now() + timedelta(hours=hours)


def _lend(items, **extra):
    extra.setdefault("borrower_name", "Anna Tran (Supplier X)")
    return lend_equipment_batch(
        LendEquipmentBatchInput(
            equipment_ids=tuple(item.pk for item in items), due_at=extra.pop("due_at", _due()), **extra
        ),
        actor=None,
    )


def _open(item):
    return EquipmentLoan.objects.filter(equipment=item, returned_at__isnull=True).first()


# Placement decides availability --------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("place", ["room", "station", "note", "none"])
def test_item_resting_anywhere_but_a_bench_can_be_lent(kind, place):
    (item,) = _items(kind, 1, prefix=f"LB-P-{place}")
    room = Room.objects.create(sku=f"LB-R-{place}", name="Store")
    target = {
        "room": {"room_id": room.pk},
        "station": {"station_id": Station.objects.create(sku=f"LB-S-{place}", name="S", room=room).pk},
        "note": {"location_note": "Cabinet 3, shelf B"},
        "none": None,
    }[place]
    if target:
        place_equipment(PlaceEquipmentInput(equipment_id=item.pk, **target), actor=None)
    _lend([item])
    assert _open(item) is not None
    assert not EquipmentPlacement.objects.filter(equipment=item, unassigned_at__isnull=True).exists()


@pytest.mark.django_db
def test_item_on_a_bench_cannot_be_lent_single_or_batch(kind):
    free, on_bench = _items(kind, 2, prefix="LB-B")
    bench = Bench.objects.create(sku="LB-BENCH", name="Bench")
    place_equipment(PlaceEquipmentInput(equipment_id=on_bench.pk, bench_id=bench.pk), actor=None)
    with pytest.raises(EquipmentNotAvailable) as error:
        hand_over_equipment(
            HandOverEquipmentInput(equipment_id=on_bench.pk, due_at=_due(), borrower_name="X"), actor=None
        )
    assert "placed on a bench" in error.value.details["reasons"]
    with pytest.raises(EquipmentNotAvailable) as error:
        _lend([free, on_bench])
    assert (
        list(error.value.details) == ["equipment_ids[1]"]
        and "placed on a bench" in error.value.details["equipment_ids[1]"]
    )
    # All or nothing: the free item was not handed over either.
    assert _open(free) is None and not EquipmentLoanBatch.objects.exists()


# Batch lending -------------------------------------------------------------------------------


@pytest.mark.django_db
def test_lend_batch_to_a_borrower_without_an_account(kind):
    items = _items(kind, 3)
    batch = _lend(
        items,
        borrower_contact="anna@example.com",
        purpose="EMC test week",
        conditions_out=((items[1].pk, "Scratched"),),
    )
    assert (
        batch.borrower is None
        and batch.borrower_label == "Anna Tran (Supplier X)"
        and batch.purpose == "EMC test week"
    )
    assert batch.loans.count() == 3
    assert _open(items[1]).condition_out == "Scratched"


@pytest.mark.django_db
def test_borrower_is_required_and_user_must_be_active(kind):
    (item,) = _items(kind, 1)
    with pytest.raises(ValidationError):
        _lend([item], borrower_name="")
    inactive = User.objects.create_user(username="lb-inactive", is_active=False)
    with pytest.raises(ValidationError):
        _lend([item], borrower_name="", borrower_id=inactive.pk)
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        EquipmentLoanBatch.objects.create()
    assert "equipment_loan_batch_has_borrower" in str(error.value)


@pytest.mark.django_db
def test_batch_input_validation(kind):
    items = _items(kind, 2)
    with pytest.raises(ValidationError):
        _lend([items[0], items[0]])
    with pytest.raises(ValidationError):
        lend_equipment_batch(LendEquipmentBatchInput(equipment_ids=(), due_at=_due(), borrower_name="X"), actor=None)
    with pytest.raises(ValidationError):
        _lend(items, due_at=timezone.now() - timedelta(minutes=1))
    with pytest.raises(ValidationError):
        _lend([items[0]], conditions_out=((items[1].pk, "not in the batch"),))


@pytest.mark.django_db
def test_reservation_by_someone_else_blocks_lending_across_its_window(kind):
    (item,) = _items(kind, 1)
    start = timezone.now() + timedelta(days=1)
    EquipmentBooking.objects.create(
        equipment=item, booking_code="LB-BK-1", starts_at=start, ends_at=start + timedelta(days=2)
    )
    with pytest.raises(EquipmentNotAvailable) as error:
        _lend([item], due_at=start + timedelta(hours=1))
    assert "reserved in that period" in error.value.details["equipment_ids[0]"]
    _lend([item], due_at=start - timedelta(hours=1))  # back before the reservation starts


@pytest.mark.django_db
def test_idempotency_key_replays_and_detects_reuse(kind):
    items = _items(kind, 2)
    first = _lend(items, idempotency_key="slip-1")
    replay = lend_equipment_batch(
        LendEquipmentBatchInput(
            equipment_ids=tuple(item.pk for item in items),
            due_at=first.loans.first().due_at,
            borrower_name="Anna Tran (Supplier X)",
            idempotency_key="slip-1",
        ),
        actor=None,
    )
    assert replay.pk == first.pk and EquipmentLoan.objects.count() == 2
    with pytest.raises(LoanIdempotencyKeyReuse):
        _lend(items, idempotency_key="slip-1", purpose="different body")


# Return and extend ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_partial_return_then_rest_and_repeat_is_noop(kind):
    items = _items(kind, 3)
    room = Room.objects.create(sku="LB-R-RET", name="Store")
    batch = _lend(items)
    returned = return_equipment_batch(
        ReturnEquipmentBatchInput(
            items=(
                ReturnEquipmentInput(equipment_id=items[0].pk, condition_in="ok", room_id=room.pk),
                ReturnEquipmentInput(equipment_id=items[1].pk, condition="out_of_service", room_id=room.pk),
            )
        ),
        actor=None,
    )
    assert {loan.equipment_id for loan in returned} == {items[0].pk, items[1].pk}
    assert _open(items[2]) is not None and batch.loans.filter(returned_at__isnull=True).count() == 1
    again = return_equipment_batch(
        ReturnEquipmentBatchInput(items=(ReturnEquipmentInput(equipment_id=items[0].pk),)), actor=None
    )
    assert again[0].pk == returned[0].pk
    with pytest.raises(EquipmentNotOnLoan):
        return_equipment_batch(
            ReturnEquipmentBatchInput(items=(ReturnEquipmentInput(equipment_id=_items(kind, 1, "LB-X")[0].pk),)),
            actor=None,
        )


@pytest.mark.django_db
def test_extend_every_open_line_of_a_batch(kind):
    items = _items(kind, 2)
    batch = _lend(items)
    later = _due(120)
    extended = extend_loans(ExtendLoansInput(due_at=later, batch_id=batch.pk), actor=None)
    assert [loan.due_at for loan in extended] == [later, later]
    with pytest.raises(ValidationError):
        extend_loans(ExtendLoansInput(due_at=later, batch_id=batch.pk, equipment_ids=(items[0].pk,)), actor=None)


# Concurrency (PostgreSQL) --------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_two_batches_sharing_an_item_one_wins_without_partial_loans(kind):
    shared, left, right = _items(kind, 3, prefix="LB-C")
    barrier = threading.Barrier(2)
    outcomes = []

    def lend(other):
        try:
            barrier.wait()
            lend_equipment_batch(
                LendEquipmentBatchInput(
                    equipment_ids=(shared.pk, other.pk), due_at=_due(), borrower_name=f"B{other.pk}"
                ),
                actor=None,
            )
            outcomes.append("ok")
        except EquipmentNotAvailable:
            outcomes.append("refused")
        finally:
            close_old_connections()

    threads = [threading.Thread(target=lend, args=(item,)) for item in (left, right)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["ok", "refused"]
    assert EquipmentLoan.objects.filter(returned_at__isnull=True).count() == 2  # the winner's two lines only
    assert EquipmentLoanBatch.objects.count() == 1
