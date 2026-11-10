"""Equipment loans: hand-over, return, extension, and their rules (redesign step 3)."""

import threading
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.utils import timezone

from core.labs.features.equipment.application import (
    ChangeConditionInput,
    ChangeLifecycleInput,
    DeleteEquipmentInput,
    ExtendLoanInput,
    HandOverEquipmentInput,
    PlaceEquipmentInput,
    ReturnEquipmentInput,
    change_condition,
    change_lifecycle,
    delete_equipment,
    extend_loan,
    hand_over_equipment,
    place_equipment,
    return_equipment,
)
from core.labs.features.equipment.exceptions import (
    EquipmentInUse,
    EquipmentNotAvailable,
    EquipmentNotOnLoan,
    EquipmentOnLoan,
    LoanManagedByBooking,
)
from core.labs.features.equipment.public import list_equipment
from core.labs.models import (
    Bench,
    ComputingEquipment,
    Equipment,
    EquipmentBooking,
    EquipmentCategory,
    EquipmentKind,
    EquipmentLoan,
    EquipmentLoanBatch,
    EquipmentPlacement,
    Room,
)

User = get_user_model()


@pytest.fixture
def kind(db):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    return EquipmentKind.objects.create(category=category, name="Loan PC")


@pytest.fixture
def unit(kind):
    return ComputingEquipment.objects.create(sku="LN-1", name="Loan unit", kind=kind)


@pytest.fixture
def borrower(db):
    return User.objects.create_user(username="ln-borrower")


def _due(hours=24):
    return timezone.now() + timedelta(hours=hours)


def _hand_over(unit, borrower, **extra):
    return hand_over_equipment(
        HandOverEquipmentInput(
            equipment_id=unit.pk, borrower_id=borrower.pk, due_at=extra.pop("due_at", _due()), **extra
        ),
        actor=None,
    )


def _return(unit, **extra):
    return return_equipment(ReturnEquipmentInput(equipment_id=unit.pk, **extra), actor=None)


def _row(unit):
    return list_equipment().get(pk=unit.pk)


# Hand over --------------------------------------------------------------------------------


@pytest.mark.django_db
def test_hand_over_opens_loan_and_leaves_the_resting_place(unit, borrower):
    room = Room.objects.create(sku="LN-R1", name="Store")
    place_equipment(PlaceEquipmentInput(equipment_id=unit.pk, room_id=room.pk), actor=None)
    loan = _hand_over(unit, borrower, condition_out="Scratched lid")
    assert loan.batch.borrower == borrower and loan.returned_at is None and loan.condition_out == "Scratched lid"
    assert not EquipmentPlacement.objects.filter(equipment=unit, unassigned_at__isnull=True).exists()
    assert _row(unit).display_status == "borrowed"


@pytest.mark.django_db
def test_second_hand_over_is_refused(unit, borrower):
    _hand_over(unit, borrower)
    with pytest.raises(EquipmentOnLoan):
        _hand_over(unit, User.objects.create_user(username="ln-other"))


@pytest.mark.django_db
def test_hand_over_for_the_same_booking_is_idempotent(unit, borrower):
    start = timezone.now()
    booking = EquipmentBooking.objects.create(equipment=unit, booking_code="LN-BK-1", starts_at=start, ends_at=_due())
    first = _hand_over(unit, borrower, booking_id=booking.pk)
    again = _hand_over(unit, borrower, booking_id=booking.pk)
    assert first.pk == again.pk
    assert EquipmentLoan.objects.filter(equipment=unit).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("setup", ["maintenance", "bench", "planned", "calibration"])
def test_hand_over_needs_an_available_unit(unit, borrower, setup):
    if setup == "maintenance":
        change_condition(ChangeConditionInput(equipment_id=unit.pk, condition="in_maintenance"), actor=None)
    elif setup == "bench":
        bench = Bench.objects.create(sku="LN-B1", name="Bench")
        place_equipment(PlaceEquipmentInput(equipment_id=unit.pk, bench_id=bench.pk), actor=None)
    elif setup == "planned":
        Equipment.objects.filter(pk=unit.pk).update(lifecycle_state="planned")
    else:
        Equipment.objects.filter(pk=unit.pk).update(calibration_required=True)
    with pytest.raises(EquipmentNotAvailable) as error:
        _hand_over(unit, borrower)
    assert error.value.details["reasons"]
    assert not EquipmentLoan.objects.filter(equipment=unit).exists()


@pytest.mark.django_db
def test_hand_over_validates_borrower_and_due_time(unit, borrower):
    inactive = User.objects.create_user(username="ln-inactive", is_active=False)
    with pytest.raises(ValidationError):
        _hand_over(unit, inactive)
    with pytest.raises(ValidationError):
        _hand_over(unit, borrower, due_at=timezone.now() - timedelta(minutes=1))


# While on loan ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_placement_is_refused_but_condition_may_change_while_on_loan(unit, borrower):
    _hand_over(unit, borrower)
    with pytest.raises(EquipmentOnLoan):
        place_equipment(PlaceEquipmentInput(equipment_id=unit.pk, location_note="Desk"), actor=None)
    change_condition(ChangeConditionInput(equipment_id=unit.pk, condition="out_of_service"), actor=None)
    assert _row(unit).display_status == "broken"  # broken outranks borrowed; the loan stays open
    assert EquipmentLoan.objects.filter(equipment=unit, returned_at__isnull=True).exists()


@pytest.mark.django_db
def test_lifecycle_rules_while_on_loan(unit, borrower):
    loan = _hand_over(unit, borrower)
    with pytest.raises(EquipmentOnLoan):
        change_lifecycle(ChangeLifecycleInput(equipment_id=unit.pk, lifecycle_state="retired"), actor=None)
    change_lifecycle(
        ChangeLifecycleInput(equipment_id=unit.pk, lifecycle_state="lost", reason="Not returned"), actor=None
    )
    loan.refresh_from_db()
    assert loan.close_reason == "lost" and loan.returned_at is not None


@pytest.mark.django_db
def test_delete_is_refused_while_on_loan(unit, borrower):
    _hand_over(unit, borrower)
    with pytest.raises(EquipmentInUse) as error:
        delete_equipment(DeleteEquipmentInput(equipment_id=unit.pk, model=ComputingEquipment), actor=None)
    assert error.value.details == {"blockers": ["loan"]}


# Return and extend ------------------------------------------------------------------------


@pytest.mark.django_db
def test_return_closes_loan_records_condition_and_place(unit, borrower):
    room = Room.objects.create(sku="LN-R2", name="Store")
    loan = _hand_over(unit, borrower)
    returned = _return(unit, condition_in="Cracked screen", condition="out_of_service", room_id=room.pk)
    assert returned.pk == loan.pk and returned.close_reason == "returned" and returned.condition_in == "Cracked screen"
    assert _return(unit).pk == loan.pk  # repeated return is a no-op
    row = _row(unit)
    assert row.display_status == "broken" and row.condition == "out_of_service"
    assert EquipmentPlacement.objects.get(equipment=unit, unassigned_at__isnull=True).room_id == room.pk


@pytest.mark.django_db
def test_return_without_a_loan_is_refused(unit):
    with pytest.raises(EquipmentNotOnLoan):
        _return(unit)


@pytest.mark.django_db
def test_extend_loan(unit, borrower):
    loan = _hand_over(unit, borrower)
    later = _due(72)
    assert extend_loan(ExtendLoanInput(equipment_id=unit.pk, due_at=later), actor=None).due_at == later
    with pytest.raises(ValidationError):
        extend_loan(ExtendLoanInput(equipment_id=unit.pk, due_at=timezone.now() - timedelta(hours=1)), actor=None)
    EquipmentLoan.objects.filter(pk=loan.pk).update(
        booking=EquipmentBooking.objects.create(
            equipment=unit, booking_code="LN-BK-2", starts_at=timezone.now(), ends_at=later
        )
    )
    with pytest.raises(LoanManagedByBooking):
        extend_loan(ExtendLoanInput(equipment_id=unit.pk, due_at=_due(96)), actor=None)


@pytest.mark.django_db
def test_overdue_is_computed(unit, borrower):
    loan = _hand_over(unit, borrower)
    EquipmentLoan.objects.filter(pk=loan.pk).update(
        handed_over_at=timezone.now() - timedelta(days=3), due_at=timezone.now() - timedelta(days=1)
    )
    row = _row(unit)
    assert row.loan_overdue is True and row.on_loan is True and row.display_status == "borrowed"


# Database guards and concurrency ----------------------------------------------------------


@pytest.mark.django_db
def test_loan_constraints(unit, borrower):
    now = timezone.now()
    batch = EquipmentLoanBatch.objects.create(borrower=borrower)
    EquipmentLoan.objects.create(equipment=unit, batch=batch, handed_over_at=now, due_at=_due())
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        EquipmentLoan.objects.create(equipment=unit, batch=batch, handed_over_at=now, due_at=_due())
    assert "one_active_loan_per_equipment" in str(error.value)
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        EquipmentLoan.objects.filter(equipment=unit).update(returned_at=now)
    assert "equipment_loan_closed_has_reason" in str(error.value)
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        EquipmentLoan.objects.filter(equipment=unit).update(due_at=now - timedelta(days=1))
    assert "equipment_loan_due_after_handover" in str(error.value)


@pytest.mark.django_db(transaction=True)
def test_concurrent_hand_overs_open_one_loan(kind):
    unit = ComputingEquipment.objects.create(sku="LN-C1", name="Concurrent", kind=kind)
    borrowers = [User.objects.create_user(username=f"ln-c{index}") for index in range(2)]
    barrier = threading.Barrier(2)
    outcomes = []

    def hand_over(user):
        try:
            barrier.wait()
            hand_over_equipment(
                HandOverEquipmentInput(equipment_id=unit.pk, borrower_id=user.pk, due_at=_due()), actor=None
            )
            outcomes.append("ok")
        except EquipmentOnLoan:
            outcomes.append("on_loan")
        finally:
            close_old_connections()

    threads = [threading.Thread(target=hand_over, args=(user,)) for user in borrowers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["ok", "on_loan"]
    assert EquipmentLoan.objects.filter(equipment=unit, returned_at__isnull=True).count() == 1
