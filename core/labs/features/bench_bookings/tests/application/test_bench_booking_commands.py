"""Command tests for bench booking create and update rules."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from core.labs.features.bench_bookings.application import (
    CreateBenchBookingInput,
    DecideBenchBookingApprovalInput,
    UpdateBenchBookingInput,
    create_bench_booking,
    decide_bench_booking_approval,
    update_bench_booking,
)
from core.labs.features.bench_bookings.application.booking_codes import generate_booking_code
from core.labs.features.bench_bookings.exceptions import (
    BenchBookingConflict,
    BenchBookingIdempotencyKeyReuse,
    BenchBookingPermissionDenied,
)
from core.labs.models import (
    AgentIdentity,
    BenchBooking,
    BookingApprovalStatus,
    BookingStatus,
    EquipmentCategory,
    EquipmentKind,
)
from core.labs.models.resource.equipment.assignment import EquipmentAssignment
from core.labs.models.resource.equipment.computing import ComputingEquipment
from core.users.public import LabsRole
from core.users.models import URSGroup
from core.users.tests.factories import UserFactory


def _decision_response(booking):
    return {"data": {"id": booking.pk, "approval_status": booking.approval_status}}


def _create(actor, bench_id, starts_at, ends_at, **extra):
    return create_bench_booking(
        actor=actor,
        data=CreateBenchBookingInput(bench_id=bench_id, starts_at=starts_at, ends_at=ends_at, **extra),
    )


def _grant_role(user, role):
    group = user.groups.create(name=f"approval-{role.value}-{user.pk}")
    URSGroup.objects.create(group=group, urs_group_id=100000 + user.pk, labs_role=role.value)
    return user


@pytest.mark.django_db
class TestBookingApprovalDecisions:
    def test_coordinator_approves_pending_reserved_booking(self, actor, make_booking, now):
        coordinator = _grant_role(UserFactory(username="booking-coordinator"), LabsRole.COORDINATOR)
        booking = make_booking(
            starts_at=now + timedelta(hours=2),
            ends_at=now + timedelta(hours=7),
        )
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save(actor=coordinator)

        updated = decide_bench_booking_approval(
            actor=coordinator,
            data=DecideBenchBookingApprovalInput(
                booking_id=booking.pk,
                decision=BookingApprovalStatus.APPROVED,
                idempotency_key=str(uuid.uuid4()),
            ),
            project_response=_decision_response,
        ).booking

        updated.refresh_from_db()
        assert updated.approval_status == BookingApprovalStatus.APPROVED
        assert updated.approved_by_id == coordinator.pk
        assert updated.approved_at is not None
        assert updated.rejection_reason == ""
        assert updated.status == BookingStatus.RESERVED

    def test_admin_rejects_pending_booking_with_reason(self, make_booking, now):
        admin = _grant_role(UserFactory(username="booking-admin"), LabsRole.ADMIN)
        booking = make_booking(
            starts_at=now + timedelta(hours=2),
            ends_at=now + timedelta(hours=7),
        )
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save(actor=admin)

        updated = decide_bench_booking_approval(
            actor=admin,
            data=DecideBenchBookingApprovalInput(
                booking_id=booking.pk,
                decision=BookingApprovalStatus.REJECTED,
                idempotency_key=str(uuid.uuid4()),
                rejection_reason="  Not enough detail  ",
            ),
            project_response=_decision_response,
        ).booking

        updated.refresh_from_db()
        assert updated.approval_status == BookingApprovalStatus.REJECTED
        assert updated.approved_by_id == admin.pk
        assert updated.approved_at is not None
        assert updated.rejection_reason == "Not enough detail"
        assert updated.status == BookingStatus.RESERVED

    def test_rejection_without_reason_is_rejected(self, make_booking, now):
        coordinator = _grant_role(UserFactory(username="booking-coordinator-no-reason"), LabsRole.COORDINATOR)
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=7))
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save(actor=coordinator)

        with pytest.raises(ValidationError) as error:
            decide_bench_booking_approval(
                actor=coordinator,
                data=DecideBenchBookingApprovalInput(
                    booking_id=booking.pk,
                    decision=BookingApprovalStatus.REJECTED,
                    idempotency_key=str(uuid.uuid4()),
                ),
                project_response=_decision_response,
            )

        assert "reason" in error.value.message_dict
        booking.refresh_from_db()
        assert booking.approval_status == BookingApprovalStatus.PENDING
        assert booking.approved_by_id is None

    def test_owner_without_role_cannot_decide(self, actor, make_booking, now):
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=7))
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save(actor=actor)

        with pytest.raises(BenchBookingPermissionDenied):
            decide_bench_booking_approval(
                actor=actor,
                data=DecideBenchBookingApprovalInput(
                    booking_id=booking.pk,
                    decision=BookingApprovalStatus.APPROVED,
                    idempotency_key=str(uuid.uuid4()),
                ),
                project_response=_decision_response,
            )

        booking.refresh_from_db()
        assert booking.approval_status == BookingApprovalStatus.PENDING

    def test_repeated_or_reversed_decision_conflicts(self, make_booking, now):
        coordinator = _grant_role(UserFactory(username="booking-coordinator-repeat"), LabsRole.COORDINATOR)
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=7))
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save(actor=coordinator)
        command = DecideBenchBookingApprovalInput(
            booking_id=booking.pk,
            decision=BookingApprovalStatus.APPROVED,
            idempotency_key=str(uuid.uuid4()),
        )
        decide_bench_booking_approval(actor=coordinator, data=command, project_response=_decision_response)
        booking.refresh_from_db()
        approved_at = booking.approved_at

        with pytest.raises(BenchBookingConflict):
            decide_bench_booking_approval(
                actor=coordinator,
                data=DecideBenchBookingApprovalInput(
                    booking_id=booking.pk,
                    decision=BookingApprovalStatus.APPROVED,
                    idempotency_key=str(uuid.uuid4()),
                ),
                project_response=_decision_response,
            )
        booking.refresh_from_db()
        assert booking.approval_status == BookingApprovalStatus.APPROVED
        assert booking.approved_at == approved_at

    def test_matching_key_replays_original_response(self, make_booking, now):
        coordinator = _grant_role(UserFactory(username="booking-coordinator-replay"), LabsRole.COORDINATOR)
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=7))
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save(actor=coordinator)
        command = DecideBenchBookingApprovalInput(
            booking_id=booking.pk,
            decision=BookingApprovalStatus.APPROVED,
            idempotency_key=str(uuid.uuid4()),
        )

        first = decide_bench_booking_approval(
            actor=coordinator,
            data=command,
            project_response=_decision_response,
        )
        replay = decide_bench_booking_approval(
            actor=coordinator,
            data=command,
            project_response=_decision_response,
        )

        assert first.replayed is False
        assert replay.replayed is True
        assert replay.status_code == first.status_code
        assert replay.response_body == first.response_body
        assert booking.decision_receipts.count() == 1

    def test_same_key_on_different_action_path_is_rejected(self, make_booking, now):
        coordinator = _grant_role(UserFactory(username="booking-coordinator-cross-path"), LabsRole.COORDINATOR)
        first_booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=7))
        second_booking = make_booking(starts_at=now + timedelta(hours=8), ends_at=now + timedelta(hours=13))
        first_booking.approval_status = BookingApprovalStatus.PENDING
        second_booking.approval_status = BookingApprovalStatus.PENDING
        first_booking.save(actor=coordinator)
        second_booking.save(actor=coordinator)
        key = str(uuid.uuid4())
        decide_bench_booking_approval(
            actor=coordinator,
            data=DecideBenchBookingApprovalInput(
                booking_id=first_booking.pk,
                decision=BookingApprovalStatus.APPROVED,
                idempotency_key=key,
            ),
            project_response=_decision_response,
        )

        with pytest.raises(BenchBookingIdempotencyKeyReuse):
            decide_bench_booking_approval(
                actor=coordinator,
                data=DecideBenchBookingApprovalInput(
                    booking_id=second_booking.pk,
                    decision=BookingApprovalStatus.APPROVED,
                    idempotency_key=key,
                ),
                project_response=_decision_response,
            )


    def test_expired_key_can_be_reused(self, make_booking, now):
        coordinator = _grant_role(UserFactory(username="booking-coordinator-expired-key"), LabsRole.COORDINATOR)
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=7))
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save(actor=coordinator)
        key = str(uuid.uuid4())

        first = decide_bench_booking_approval(
            actor=coordinator,
            data=DecideBenchBookingApprovalInput(
                booking_id=booking.pk,
                decision=BookingApprovalStatus.APPROVED,
                idempotency_key=key,
            ),
            project_response=_decision_response,
        )
        booking.decision_receipts.update(expires_at=timezone.now() - timedelta(seconds=1))
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save(actor=coordinator)

        reused = decide_bench_booking_approval(
            actor=coordinator,
            data=DecideBenchBookingApprovalInput(
                booking_id=booking.pk,
                decision=BookingApprovalStatus.APPROVED,
                idempotency_key=key,
            ),
            project_response=_decision_response,
        )

        assert first.replayed is False
        assert reused.replayed is False
        assert booking.decision_receipts.count() == 1

    @pytest.mark.skipif(connection.vendor != "postgresql", reason="advisory-lock guarantee is PostgreSQL-specific")
    @pytest.mark.django_db(transaction=True)
    def test_simultaneous_same_key_requests_produce_one_decision_and_one_replay(self, make_booking, now):
        coordinator = _grant_role(UserFactory(username="booking-coordinator-concurrent"), LabsRole.COORDINATOR)
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=7))
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save(actor=coordinator)
        key = str(uuid.uuid4())
        barrier = Barrier(2)

        def decide():
            close_old_connections()
            try:
                actor = type(coordinator).objects.get(pk=coordinator.pk)
                barrier.wait(timeout=10)
                return decide_bench_booking_approval(
                    actor=actor,
                    data=DecideBenchBookingApprovalInput(
                        booking_id=booking.pk,
                        decision=BookingApprovalStatus.APPROVED,
                        idempotency_key=key,
                    ),
                    project_response=_decision_response,
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [future.result(timeout=30) for future in (executor.submit(decide), executor.submit(decide))]

        assert sorted(result.replayed for result in results) == [False, True]
        assert results[0].response_body == results[1].response_body
        assert BenchBooking.objects.get(pk=booking.pk).approval_status == BookingApprovalStatus.APPROVED
        assert booking.decision_receipts.count() == 1

    @pytest.mark.skipif(connection.vendor != "postgresql", reason="advisory-lock guarantee is PostgreSQL-specific")
    @pytest.mark.django_db(transaction=True)
    def test_distinct_keys_cannot_commit_opposite_decisions(self, make_booking, now):
        coordinator = _grant_role(UserFactory(username="booking-coordinator-distinct-keys"), LabsRole.COORDINATOR)
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=7))
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save(actor=coordinator)
        barrier = Barrier(2)

        def decide(decision):
            close_old_connections()
            try:
                actor = type(coordinator).objects.get(pk=coordinator.pk)
                barrier.wait(timeout=10)
                return decide_bench_booking_approval(
                    actor=actor,
                    data=DecideBenchBookingApprovalInput(
                        booking_id=booking.pk,
                        decision=decision,
                        idempotency_key=str(uuid.uuid4()),
                        rejection_reason="Not approved" if decision == BookingApprovalStatus.REJECTED else "",
                    ),
                    project_response=_decision_response,
                )
            except BenchBookingConflict:
                return None
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [
                future.result(timeout=30)
                for future in (
                    executor.submit(decide, BookingApprovalStatus.APPROVED),
                    executor.submit(decide, BookingApprovalStatus.REJECTED),
                )
            ]

        committed = [result for result in results if result is not None]
        assert len(committed) == 1
        assert BenchBooking.objects.get(pk=booking.pk).approval_status in {
            BookingApprovalStatus.APPROVED,
            BookingApprovalStatus.REJECTED,
        }
        assert booking.decision_receipts.count() == 1

    def test_only_reserved_pending_booking_can_be_decided(self, make_booking, now):
        coordinator = _grant_role(UserFactory(username="booking-coordinator-in-progress"), LabsRole.COORDINATOR)
        booking = make_booking(
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(hours=2),
            status=BookingStatus.IN_PROGRESS,
        )
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save(actor=coordinator)

        with pytest.raises(BenchBookingConflict):
            decide_bench_booking_approval(
                actor=coordinator,
                data=DecideBenchBookingApprovalInput(
                    booking_id=booking.pk,
                    decision=BookingApprovalStatus.APPROVED,
                    idempotency_key=str(uuid.uuid4()),
                ),
            )


@pytest.mark.django_db
class TestCreate:
    def test_accepts_start_up_to_ten_minutes_in_the_past(self, actor, bench, now):
        # Acceptance example: at 11:40, a booking starting 11:30 is accepted.
        # A small margin keeps the test stable: the command reads the clock after the fixture.
        booking = _create(actor, bench.pk, now - timedelta(minutes=9, seconds=59), now + timedelta(hours=1))
        assert booking.pk is not None
        assert booking.booking_code.startswith("BOOKING-")

    def test_booking_code_is_hash_derived_and_unique_per_generation(self, bench, now):
        first_code = generate_booking_code(
            bench_id=bench.pk,
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
        )
        second_code = generate_booking_code(
            bench_id=bench.pk,
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
        )
        assert first_code.startswith("BOOKING-")
        assert len(first_code) == len("BOOKING-") + 14
        assert first_code != second_code

    def test_rejects_start_more_than_ten_minutes_in_the_past(self, actor, bench, now):
        with pytest.raises(ValidationError) as exc:
            _create(actor, bench.pk, now - timedelta(minutes=10, seconds=1), now + timedelta(hours=1))
        assert "starts_at" in exc.value.message_dict

    def test_rejects_end_not_after_start(self, actor, bench, future_window):
        starts_at, _ = future_window
        with pytest.raises(ValidationError):
            _create(actor, bench.pk, starts_at, starts_at)

    def test_rejects_booking_shorter_than_ten_minutes(self, actor, bench, now):
        starts_at = now + timedelta(hours=2)
        with pytest.raises(ValidationError) as exc:
            _create(actor, bench.pk, starts_at, starts_at + timedelta(minutes=9, seconds=59))
        assert "ends_at" in exc.value.message_dict

    def test_accepts_ten_minute_booking(self, actor, bench, now):
        starts_at = now + timedelta(hours=2)
        booking = _create(actor, bench.pk, starts_at, starts_at + timedelta(minutes=10))
        assert booking.pk is not None

    def test_long_booking_requires_approval(self, actor, bench, now):
        starts_at = now + timedelta(hours=2)
        booking = _create(actor, bench.pk, starts_at, starts_at + timedelta(hours=4, seconds=1))
        assert booking.approval_status == BookingApprovalStatus.PENDING

    def test_booking_at_approval_threshold_is_approved(self, actor, bench, now):
        starts_at = now + timedelta(hours=2)
        booking = _create(actor, bench.pk, starts_at, starts_at + timedelta(hours=4))
        assert booking.approval_status == BookingApprovalStatus.APPROVED

    def test_rejects_overlapping_existing_booking(self, actor, bench, make_booking, now):
        existing_end = now + timedelta(hours=3)
        make_booking(starts_at=now + timedelta(hours=2), ends_at=existing_end)
        with pytest.raises(BenchBookingConflict):
            _create(actor, bench.pk, existing_end - timedelta(minutes=1), existing_end + timedelta(hours=1))

    def test_accepts_immediately_after_existing_booking(self, actor, bench, make_booking, now):
        existing_end = now + timedelta(hours=3)
        make_booking(starts_at=now + timedelta(hours=2), ends_at=existing_end)
        booking = _create(
            actor,
            bench.pk,
            existing_end,
            existing_end + timedelta(hours=1),
        )
        assert booking.pk is not None

    def test_accepts_immediately_before_existing_booking(self, actor, bench, make_booking, now):
        existing_start = now + timedelta(hours=3)
        make_booking(starts_at=existing_start, ends_at=now + timedelta(hours=4))
        booking = _create(actor, bench.pk, now + timedelta(hours=2), existing_start)
        assert booking.pk is not None

    def test_other_bench_is_not_blocked(self, actor, bench, other_bench, make_booking, now):
        make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=3))
        booking = _create(actor, other_bench.pk, now + timedelta(hours=2), now + timedelta(hours=3))
        assert booking.bench_id == other_bench.pk

    def test_cancelled_booking_does_not_block(self, actor, bench, make_booking, now):
        make_booking(
            starts_at=now + timedelta(hours=2),
            ends_at=now + timedelta(hours=3),
            status=BookingStatus.CANCELLED,
        )
        booking = _create(actor, bench.pk, now + timedelta(hours=2), now + timedelta(hours=3))
        assert booking.pk is not None


@pytest.mark.django_db
class TestUpdate:
    def test_updates_reason_while_in_progress(self, actor, bench, make_booking, now):
        booking = make_booking(
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=1),
            status=BookingStatus.IN_PROGRESS,
        )
        updated = update_bench_booking(
            actor=actor,
            data=UpdateBenchBookingInput(booking_id=booking.pk, fields={"reason": "Calibration"}),
        )
        assert updated.reason == "Calibration"

    def test_rejects_start_change_while_in_progress(self, actor, bench, make_booking, now):
        booking = make_booking(
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=1),
            status=BookingStatus.IN_PROGRESS,
        )
        with pytest.raises(BenchBookingConflict):
            update_bench_booking(
                actor=actor,
                data=UpdateBenchBookingInput(
                    booking_id=booking.pk,
                    fields={"starts_at": now - timedelta(minutes=2)},
                ),
            )

    def test_rejects_bench_change_while_in_progress(self, actor, bench, other_bench, make_booking, now):
        booking = make_booking(
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=1),
            status=BookingStatus.IN_PROGRESS,
        )
        with pytest.raises(BenchBookingConflict):
            update_bench_booking(
                actor=actor,
                data=UpdateBenchBookingInput(booking_id=booking.pk, fields={"bench_id": other_bench.pk}),
            )

    def test_rejects_unknown_field(self, actor, make_booking, now):
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=3))
        with pytest.raises(ValidationError):
            update_bench_booking(
                actor=actor,
                data=UpdateBenchBookingInput(booking_id=booking.pk, fields={"unknown_field": "invalid"}),
            )

    def test_reserved_booking_can_transition_to_cancelled(self, actor, make_booking, now):
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=3))

        updated = update_bench_booking(
            actor=actor,
            data=UpdateBenchBookingInput(booking_id=booking.pk, fields={"status": BookingStatus.CANCELLED}),
        )

        assert updated.status == BookingStatus.CANCELLED

    def test_patch_command_cannot_set_expired_status(self, actor, make_booking, now):
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=3))

        with pytest.raises(ValidationError) as error:
            update_bench_booking(
                actor=actor,
                data=UpdateBenchBookingInput(booking_id=booking.pk, fields={"status": BookingStatus.EXPIRED}),
            )

        assert error.value.message_dict["status"] == ["Expired status is managed automatically."]

    def test_patch_command_cannot_set_in_progress_status(self, actor, make_booking, now):
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=3))

        with pytest.raises(ValidationError) as error:
            update_bench_booking(
                actor=actor,
                data=UpdateBenchBookingInput(booking_id=booking.pk, fields={"status": BookingStatus.IN_PROGRESS}),
            )

        assert error.value.message_dict["status"] == ["In progress status is managed automatically."]

    def test_terminal_booking_cannot_return_to_reserved(self, actor, make_booking, now):
        booking = make_booking(
            starts_at=now - timedelta(hours=1),
            ends_at=now,
            status=BookingStatus.COMPLETED,
        )

        with pytest.raises(ValidationError):
            update_bench_booking(
                actor=actor,
                data=UpdateBenchBookingInput(booking_id=booking.pk, fields={"status": BookingStatus.RESERVED}),
            )

    def test_moving_end_into_buffer_of_neighbour_is_rejected(self, actor, bench, make_booking, now):
        booking = make_booking(starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=2))
        make_booking(starts_at=now + timedelta(hours=2, minutes=5), ends_at=now + timedelta(hours=3))
        with pytest.raises(BenchBookingConflict):
            update_bench_booking(
                actor=actor,
                data=UpdateBenchBookingInput(
                    booking_id=booking.pk, fields={"ends_at": now + timedelta(hours=2, minutes=10)}
                ),
            )

    def test_reserved_booking_can_move_bench(self, actor, bench, other_bench, make_booking, now):
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=3))
        updated = update_bench_booking(
            actor=actor,
            data=UpdateBenchBookingInput(booking_id=booking.pk, fields={"bench_id": other_bench.pk}),
        )
        assert updated.bench_id == other_bench.pk
        assert BenchBooking.objects.get(pk=booking.pk).bench_id == other_bench.pk

    def test_extending_booking_over_four_hours_requires_new_approval(self, actor, make_booking, now):
        booking = make_booking(
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=5),
        )
        booking.approved_by = actor
        booking.approved_at = now
        booking.save(update_fields=("approved_by", "approved_at"))

        updated = update_bench_booking(
            actor=actor,
            data=UpdateBenchBookingInput(
                booking_id=booking.pk,
                fields={"ends_at": now + timedelta(hours=5, microseconds=1)},
            ),
        )

        assert updated.approval_status == BookingApprovalStatus.PENDING
        assert updated.approved_by_id is None
        assert updated.approved_at is None

    def test_schedule_update_at_four_hours_remains_approved(self, actor, make_booking, now):
        booking = make_booking(
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=4),
        )
        booking.approved_by = actor
        booking.approved_at = now
        booking.save(update_fields=("approved_by", "approved_at"))

        updated = update_bench_booking(
            actor=actor,
            data=UpdateBenchBookingInput(
                booking_id=booking.pk,
                fields={"ends_at": now + timedelta(hours=5)},
            ),
        )

        assert updated.approval_status == BookingApprovalStatus.APPROVED
        assert updated.approved_by_id == actor.pk
        assert updated.approved_at == now


@pytest.mark.django_db(transaction=True)
class TestAgentEndTimeUpdate:
    def _linked_equipment(self, bench):
        category, _ = EquipmentCategory.objects.get_or_create(
            name="Computing", defaults={"definition": "Computing equipment"}
        )
        kind, _ = EquipmentKind.objects.get_or_create(category=category, name="Computer")
        equipment = ComputingEquipment.objects.create(
            sku=f"AGENT-BOOKING-{uuid.uuid4().hex[:8]}",
            kind=kind,
            name="Agent host",
        )
        AgentIdentity.objects.create(
            equipment=equipment,
            state=AgentIdentity.State.ACTIVE,
            public_key="test-public-key",
            public_key_sha256=uuid.uuid4().hex,
        )
        EquipmentAssignment.objects.create(equipment=equipment, bench=bench, assigned_at=timezone.now())
        return equipment

    def test_updates_only_end_time_for_associated_equipment(self, bench, make_booking, now):
        from core.labs.features.bench_bookings.application import (
            AgentBookingEndTimeInput,
            update_agent_booking_end_time,
        )

        equipment = self._linked_equipment(bench)
        identity = AgentIdentity.objects.get(equipment=equipment)
        booking = make_booking(starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=2))
        original = (booking.starts_at, booking.bench_id, booking.reason, booking.status, booking.approval_status)
        updated = update_agent_booking_end_time(
            AgentBookingEndTimeInput(
                booking_id=booking.pk,
                agent_uid=identity.agent_uid,
                ends_at=now + timedelta(hours=3),
                request_id="req-agent-end-time-1",
            ),
            actor=object(),
        )

        updated.refresh_from_db()
        assert updated.ends_at == now + timedelta(hours=3)

        assert (
            updated.starts_at,
            updated.bench_id,
            updated.reason,
            updated.status,
            updated.approval_status,
        ) == original

    def test_extending_agent_booking_over_four_hours_requires_new_approval(self, actor, bench, make_booking, now):
        from core.labs.features.bench_bookings.application import (
            AgentBookingEndTimeInput,
            update_agent_booking_end_time,
        )

        equipment = self._linked_equipment(bench)
        identity = AgentIdentity.objects.get(equipment=equipment)
        booking = make_booking(starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=5))
        booking.approved_by = actor
        booking.approved_at = now
        booking.save(update_fields=("approved_by", "approved_at"))

        updated = update_agent_booking_end_time(
            AgentBookingEndTimeInput(
                booking_id=booking.pk,
                agent_uid=identity.agent_uid,
                ends_at=now + timedelta(hours=5, microseconds=1),
                request_id="req-agent-cross-approval-threshold",
            ),
            actor=object(),
        )

        assert updated.approval_status == BookingApprovalStatus.PENDING
        assert updated.approved_by_id is None
        assert updated.approved_at is None

    def test_agent_schedule_at_four_hours_preserves_approval(self, actor, bench, make_booking, now):
        from core.labs.features.bench_bookings.application import (
            AgentBookingEndTimeInput,
            update_agent_booking_end_time,
        )

        equipment = self._linked_equipment(bench)
        identity = AgentIdentity.objects.get(equipment=equipment)
        booking = make_booking(starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=4))
        booking.approved_by = actor
        booking.approved_at = now
        booking.save(update_fields=("approved_by", "approved_at"))

        updated = update_agent_booking_end_time(
            AgentBookingEndTimeInput(
                booking_id=booking.pk,
                agent_uid=identity.agent_uid,
                ends_at=now + timedelta(hours=5),
                request_id="req-agent-at-approval-threshold",
            ),
            actor=object(),
        )

        assert updated.approval_status == BookingApprovalStatus.APPROVED
        assert updated.approved_by_id == actor.pk
        assert updated.approved_at == now

    def test_unassignment_waits_for_agent_booking_owner_lock(self, bench, make_booking, now):
        from core.labs.features.bench_bookings.application import (
            AgentBookingEndTimeInput,
            update_agent_booking_end_time,
        )
        from core.labs.features.equipment.public import UnassignEquipmentInput, unassign_equipment

        equipment = self._linked_equipment(bench)
        identity = AgentIdentity.objects.get(equipment=equipment)
        booking = make_booking(starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=2))
        barrier = Barrier(2)
        owner_lock_held = Event()
        unassignment_started = Event()
        release_booking = Event()

        def update_booking():
            close_old_connections()
            try:

                def lock_and_pause(*, equipment_id):
                    from core.labs.features.equipment.queries.equipment import (
                        lock_active_equipment_bench_assignment as lock_assignment,
                    )

                    assignment = lock_assignment(equipment_id=equipment_id)
                    owner_lock_held.set()
                    assert release_booking.wait(timeout=10)
                    return assignment

                from unittest.mock import patch

                with patch(
                    "core.labs.features.bench_bookings.application.update_agent_booking_end_time"
                    ".lock_active_equipment_bench_assignment",
                    side_effect=lock_and_pause,
                ):
                    barrier.wait(timeout=10)
                    result = update_agent_booking_end_time(
                        AgentBookingEndTimeInput(
                            booking_id=booking.pk,
                            agent_uid=identity.agent_uid,
                            ends_at=now + timedelta(hours=3),
                            request_id="req-agent-end-time-unassign-race",
                        ),
                        actor=object(),
                    )
                return "updated", result.ends_at
            except Exception as error:
                return "error", error
            finally:
                close_old_connections()

        def unassign():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                assert owner_lock_held.wait(timeout=10)
                unassignment_started.set()
                result = unassign_equipment(UnassignEquipmentInput(equipment_id=equipment.pk), actor=None)
                return "unassigned", result.pk if result else None
            except Exception as error:
                return "error", error
            finally:
                close_old_connections()

        assert connection.vendor == "postgresql"
        with ThreadPoolExecutor(max_workers=2) as pool:
            booking_future = pool.submit(update_booking)
            unassign_future = pool.submit(unassign)
            try:
                assert owner_lock_held.wait(timeout=10)
                assert unassignment_started.wait(timeout=10)
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND wait_event_type = 'Lock' "
                        "AND query ILIKE '%FOR UPDATE%'"
                        ")"
                    )
                    assert cursor.fetchone()[0]
                release_booking.set()
                booking_result = booking_future.result(timeout=15)
                unassign_result = unassign_future.result(timeout=15)
            finally:
                release_booking.set()

        assert booking_result == ("updated", now + timedelta(hours=3))
        assert unassign_result[0] == "unassigned"
        assert unassign_result[1] is not None
        booking.refresh_from_db()
        assert booking.ends_at == now + timedelta(hours=3)
        assert not EquipmentAssignment.objects.filter(equipment_id=equipment.pk, unassigned_at__isnull=True).exists()

    def test_owner_lock_helper_requires_transaction(self, bench):
        from core.labs.features.equipment.public import lock_active_equipment_bench_assignment

        equipment = self._linked_equipment(bench)
        assert connection.vendor == "postgresql"
        with pytest.raises(transaction.TransactionManagementError):
            lock_active_equipment_bench_assignment(equipment_id=equipment.pk)

    def test_rejects_unassigned_equipment_without_mutation(self, bench, make_booking, now):
        from core.labs.features.bench_bookings.application import (
            AgentBookingEndTimeInput,
            update_agent_booking_end_time,
        )

        category = EquipmentCategory.objects.create(name="Computing", definition="Computing equipment")
        kind = EquipmentKind.objects.create(category=category, name="Computer")
        equipment = ComputingEquipment.objects.create(
            sku=f"AGENT-BOOKING-{uuid.uuid4().hex[:8]}", kind=kind, name="Unassigned"
        )
        identity = AgentIdentity.objects.create(
            equipment=equipment,
            state=AgentIdentity.State.ACTIVE,
            public_key="test-public-key",
            public_key_sha256=uuid.uuid4().hex,
        )
        booking = make_booking(starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=2))
        with pytest.raises(BenchBookingConflict):
            update_agent_booking_end_time(
                AgentBookingEndTimeInput(booking.pk, identity.agent_uid, now + timedelta(hours=3), "req-2"),
                actor=object(),
            )
        booking.refresh_from_db()
        assert booking.ends_at == now + timedelta(hours=2)

    def test_assignment_owner_lock_is_held_until_booking_command_finishes(self, bench, make_booking, now):
        from core.labs.features.bench_bookings.application import (
            AgentBookingEndTimeInput,
            update_agent_booking_end_time,
        )
        from core.labs.features.equipment.public import lock_active_equipment_bench_assignment

        equipment = self._linked_equipment(bench)
        identity = AgentIdentity.objects.get(equipment=equipment)
        assignment = lock_active_equipment_bench_assignment(equipment_id=equipment.pk)

        assert assignment is not None
        assert assignment.bench_id == bench.pk

        booking = make_booking(starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=2))
        updated = update_agent_booking_end_time(
            AgentBookingEndTimeInput(
                booking_id=booking.pk,
                agent_uid=identity.agent_uid,
                ends_at=now + timedelta(hours=3),
                request_id="req-agent-end-time-owner-lock",
            ),
            actor=object(),
        )

        assert updated.ends_at == now + timedelta(hours=3)

    def test_rejects_booking_on_another_bench_for_same_equipment(self, bench, other_bench, make_booking, now):
        from core.labs.features.bench_bookings.application import (
            AgentBookingEndTimeInput,
            update_agent_booking_end_time,
        )

        equipment = self._linked_equipment(bench)
        identity = AgentIdentity.objects.get(equipment=equipment)
        booking = make_booking(
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
            bench_obj=other_bench,
        )
        with pytest.raises(BenchBookingConflict):
            update_agent_booking_end_time(
                AgentBookingEndTimeInput(booking.pk, identity.agent_uid, now + timedelta(hours=3), "req-3"),
                actor=object(),
            )
        booking.refresh_from_db()
        assert booking.ends_at == now + timedelta(hours=2)

    def test_rejects_pending_booking_without_mutation(self, bench, make_booking, now):
        from core.labs.features.bench_bookings.application import (
            AgentBookingEndTimeInput,
            update_agent_booking_end_time,
        )

        equipment = self._linked_equipment(bench)
        identity = AgentIdentity.objects.get(equipment=equipment)
        booking = make_booking(starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=2))
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save(update_fields=("approval_status",))
        with pytest.raises(BenchBookingConflict):
            update_agent_booking_end_time(
                AgentBookingEndTimeInput(booking.pk, identity.agent_uid, now + timedelta(hours=3), "req-4"),
                actor=object(),
            )
        booking.refresh_from_db()
        assert booking.ends_at == now + timedelta(hours=2)

    def test_allows_in_progress_booking_and_rejects_too_short_period(self, bench, make_booking, now):
        from core.labs.features.bench_bookings.application import (
            AgentBookingEndTimeInput,
            update_agent_booking_end_time,
        )

        equipment = self._linked_equipment(bench)
        identity = AgentIdentity.objects.get(equipment=equipment)
        booking = make_booking(
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
            status=BookingStatus.IN_PROGRESS,
        )
        updated = update_agent_booking_end_time(
            AgentBookingEndTimeInput(booking.pk, identity.agent_uid, now + timedelta(hours=3), "req-in-progress"),
            actor=object(),
        )
        assert updated.ends_at == now + timedelta(hours=3)

        refreshed = BenchBooking.objects.get(pk=booking.pk)
        with pytest.raises(ValidationError):
            update_agent_booking_end_time(
                AgentBookingEndTimeInput(
                    booking.pk,
                    identity.agent_uid,
                    refreshed.starts_at + timedelta(minutes=5),
                    "req-too-short",
                ),
                actor=object(),
            )
        refreshed.refresh_from_db()
        assert refreshed.ends_at == now + timedelta(hours=3)

    def test_rejects_conflict_without_mutation(self, bench, make_booking, now):
        from core.labs.features.bench_bookings.application import (
            AgentBookingEndTimeInput,
            update_agent_booking_end_time,
        )

        equipment = self._linked_equipment(bench)
        identity = AgentIdentity.objects.get(equipment=equipment)
        booking = make_booking(starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=2))
        make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=3))
        with pytest.raises(BenchBookingConflict):
            update_agent_booking_end_time(
                AgentBookingEndTimeInput(booking.pk, identity.agent_uid, now + timedelta(hours=2, minutes=1), "req-5"),
                actor=object(),
            )
        booking.refresh_from_db()
        assert booking.ends_at == now + timedelta(hours=2)

    def test_records_existing_notification_intent(self, bench, actor, make_booking, now, settings):
        from core.labs.features.bench_bookings.application import (
            AgentBookingEndTimeInput,
            update_agent_booking_end_time,
        )
        from core.labs.models import BookingNotification

        settings.BOOKING_NOTIFICATIONS_ENABLED = True
        settings.BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF = now - timedelta(days=1)
        settings.BOOKING_NOTIFICATIONS_EMAIL_ENABLED = True
        equipment = self._linked_equipment(bench)
        identity = AgentIdentity.objects.get(equipment=equipment)
        booking = make_booking(starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=2))
        booking.creator = actor
        booking.save(update_fields=("creator",))
        update_agent_booking_end_time(
            AgentBookingEndTimeInput(
                booking_id=booking.pk,
                agent_uid=identity.agent_uid,
                ends_at=now + timedelta(hours=3),
                request_id="req-agent-end-time-notify",
            ),
            actor=object(),
        )

        notification = BookingNotification.objects.get(booking=booking, kind="updated")
        assert notification.snapshot["ends_at"].startswith((now + timedelta(hours=3)).isoformat()[:19])

        update_agent_booking_end_time(
            AgentBookingEndTimeInput(
                booking_id=booking.pk,
                agent_uid=identity.agent_uid,
                ends_at=now + timedelta(hours=3),
                request_id="req-agent-end-time-repeat",
            ),
            actor=object(),
        )
        assert BookingNotification.objects.filter(booking=booking, kind="updated").count() == 1

    def test_rejects_unrelated_or_revoked_agent_identity(self, bench, other_bench, make_booking, now):
        from core.agents.application import transition_agent_state
        from core.labs.features.bench_bookings.application import (
            AgentBookingEndTimeInput,
            update_agent_booking_end_time,
        )

        equipment = self._linked_equipment(bench)
        linked_identity = AgentIdentity.objects.get(equipment=equipment)
        unrelated_equipment = self._linked_equipment(other_bench)
        unrelated_identity = AgentIdentity.objects.get(equipment=unrelated_equipment)
        booking = make_booking(starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=2))

        for agent_uid in (unrelated_identity.agent_uid, uuid.uuid4()):
            with pytest.raises(BenchBookingConflict):
                update_agent_booking_end_time(
                    AgentBookingEndTimeInput(booking.pk, agent_uid, now + timedelta(hours=3), "req-unrelated-agent"),
                    actor=object(),
                )

        transition_agent_state(linked_identity.agent_uid, AgentIdentity.State.REVOKED, actor=object())
        with pytest.raises(BenchBookingConflict):
            update_agent_booking_end_time(
                AgentBookingEndTimeInput(
                    booking.pk, linked_identity.agent_uid, now + timedelta(hours=3), "req-revoked-agent"
                ),
                actor=object(),
            )
        booking.refresh_from_db()
        assert booking.ends_at == now + timedelta(hours=2)
