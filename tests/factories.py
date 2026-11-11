"""Model factories for test data generation using factory-boy."""
from __future__ import annotations

import uuid
from datetime import timedelta

import factory
from django.utils import timezone

from core.labs.models import (
    ActiveLaboratoryObservation,
    ActiveUserObservation,
    AnalyticsGranularity,
    AnalyticsSource,
    Bench,
    BenchBooking,
    BenchFavorite,
    BenchGroup,
    BookingApprovalStatus,
    BookingStatus,
    BookingVolumeObservation,
    ComputingActivity,
    ComputingActivityStatus,
    EquipmentAssignment,
    EquipmentCategory,
    EquipmentKind,
    EquipmentStatus,
    EquipmentStatusRecord,
    LaboratoryVisitEvent,
    LabProject,
    LabSessionLog,
    MonitoringEvent,
    ProjectUsageObservation,
    StorageQuotaMeasurement,
    VisitorVolumeObservation,
)
from core.labs.models.resource.equipment.computing import ComputingEquipment, TechnicalUser
from core.users.models import URSGroup, User

_LABS_ROLE_URS_IDS = iter(range(700000, 799999))


def grant_labs_role(user: User, role: str = "coord") -> User:
    """Give ``user`` a Labs role through a URS group, as production does. Returns ``user``."""
    from django.contrib.auth.models import Group

    group, _ = Group.objects.get_or_create(name=f"test-labs-{role}")
    URSGroup.objects.get_or_create(group=group, defaults={"urs_group_id": next(_LABS_ROLE_URS_IDS), "labs_role": role})
    user.groups.add(group)
    if hasattr(user, "_labs_roles_cache"):
        del user._labs_roles_cache
    return user


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"testuser{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@test.com")
    password = factory.PostGenerationMethodCall("set_password", "testpass123")
    is_active = True


class TechnicalUserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TechnicalUser

    username = factory.Sequence(lambda n: f"techuser{n}")


class BenchGroupFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BenchGroup

    name = factory.Sequence(lambda n: f"Bench Group {n}")


class BenchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Bench

    sku = factory.Sequence(lambda n: f"BENCH-{n:04d}")
    name = factory.Sequence(lambda n: f"Bench {n}")


class EquipmentCategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EquipmentCategory
        django_get_or_create = ("name",)

    name = "Computing"
    definition = "Computing devices and computers"


class EquipmentKindFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EquipmentKind
        django_get_or_create = ("name", "category")

    category = factory.SubFactory(EquipmentCategoryFactory)
    name = "Computer"


class ComputingEquipmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ComputingEquipment

    sku = factory.Sequence(lambda n: f"COMP-{n:04d}")
    name = factory.Sequence(lambda n: f"Computing Station {n}")
    kind = factory.SubFactory(EquipmentKindFactory)
    os_name = "Ubuntu 22.04"


class EquipmentStatusRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EquipmentStatusRecord

    equipment = factory.SubFactory(ComputingEquipmentFactory)
    status = EquipmentStatus.AVAILABLE


class LabProjectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LabProject

    project_name = factory.Sequence(lambda n: f"Project {n}")


class BenchBookingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BenchBooking

    bench = factory.SubFactory(BenchFactory)
    project = factory.SubFactory(LabProjectFactory)
    starts_at = factory.LazyFunction(lambda: timezone.now() + timedelta(hours=1))
    ends_at = factory.LazyFunction(lambda: timezone.now() + timedelta(hours=3))
    booking_code = factory.Sequence(lambda n: f"BOOKING-{n:014d}")
    status = BookingStatus.RESERVED
    approval_status = BookingApprovalStatus.APPROVED
    # The database requires reasons for cancelled and rejected bookings.
    cancellation_reason = factory.LazyAttribute(
        lambda o: "Cancelled in test setup" if o.status == BookingStatus.CANCELLED else ""
    )
    rejection_reason = factory.LazyAttribute(
        lambda o: "Rejected in test setup" if o.approval_status == BookingApprovalStatus.REJECTED else ""
    )


class LabSessionLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LabSessionLog

    computing_equipment = factory.SubFactory(ComputingEquipmentFactory)
    login_time = factory.LazyFunction(lambda: timezone.now() - timedelta(hours=2))
    logout_time = factory.LazyFunction(lambda: timezone.now() - timedelta(hours=1))
    remote_user = "testuser"
    remote_user_display_name = "Test User"
    agent_id = "agent-test-01"
    event_id = factory.LazyFunction(uuid.uuid4)
    reported_at = factory.LazyFunction(timezone.now)


class LaboratoryVisitEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LaboratoryVisitEvent

    occurred_at = factory.LazyFunction(timezone.now)
    source = AnalyticsSource.APPLICATION
    facility_identifier = "Main Facility"


class StorageQuotaMeasurementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StorageQuotaMeasurement

    account_identifier = factory.Sequence(lambda n: f"user{n}")
    account_display_name = factory.LazyAttribute(lambda o: f"Display {o.account_identifier}")
    computer_identifier = "COMP-0001"
    used_gibibytes = 80.0
    quota_gibibytes = 100.0
    source = AnalyticsSource.COLLECTOR
    measured_at = factory.LazyFunction(timezone.now)


class BookingVolumeObservationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BookingVolumeObservation

    booking_count = 5
    period_start = factory.LazyFunction(lambda: timezone.now().replace(hour=0, minute=0, second=0, microsecond=0))
    period_end = factory.LazyAttribute(lambda o: o.period_start + timedelta(days=1))
    recorded_at = factory.LazyFunction(timezone.now)
    granularity = AnalyticsGranularity.DAILY
    source = factory.Sequence(lambda n: f"src_bv_{n}")


class ActiveLaboratoryObservationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ActiveLaboratoryObservation

    active_laboratory_count = 2
    period_start = factory.LazyFunction(lambda: timezone.now().replace(hour=0, minute=0, second=0, microsecond=0))
    period_end = factory.LazyAttribute(lambda o: o.period_start + timedelta(days=1))
    recorded_at = factory.LazyFunction(timezone.now)
    granularity = AnalyticsGranularity.DAILY
    source = factory.Sequence(lambda n: f"src_alo_{n}")


class ActiveUserObservationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ActiveUserObservation

    active_user_count = 3
    period_start = factory.LazyFunction(lambda: timezone.now().replace(hour=0, minute=0, second=0, microsecond=0))
    period_end = factory.LazyAttribute(lambda o: o.period_start + timedelta(days=1))
    recorded_at = factory.LazyFunction(timezone.now)
    granularity = AnalyticsGranularity.DAILY
    source = factory.Sequence(lambda n: f"src_auo_{n}")


class VisitorVolumeObservationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = VisitorVolumeObservation

    distinct_visitor_count = 10
    period_start = factory.LazyFunction(lambda: timezone.now().replace(hour=0, minute=0, second=0, microsecond=0))
    period_end = factory.LazyAttribute(lambda o: o.period_start + timedelta(days=1))
    recorded_at = factory.LazyFunction(timezone.now)
    granularity = AnalyticsGranularity.DAILY
    source = factory.Sequence(lambda n: f"src_vvo_{n}")


class ProjectUsageObservationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProjectUsageObservation

    project = factory.SubFactory(LabProjectFactory)
    booking_count = 2
    booked_seconds = 7200
    period_start = factory.LazyFunction(lambda: timezone.now().replace(hour=0, minute=0, second=0, microsecond=0))
    period_end = factory.LazyAttribute(lambda o: o.period_start + timedelta(days=1))
    recorded_at = factory.LazyFunction(timezone.now)
    granularity = AnalyticsGranularity.DAILY
    source = AnalyticsSource.APPLICATION


class MonitoringEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MonitoringEvent

    event_type = "status_change"
    source = "agent"
    category = "system"


class BenchFavoriteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BenchFavorite

    user = factory.SubFactory(UserFactory)
    bench = factory.SubFactory(BenchFactory)


LabComputerFactory = ComputingEquipmentFactory


class LabEquipmentAssignmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EquipmentAssignment

    bench = factory.SubFactory(BenchFactory)
    equipment = factory.SubFactory(ComputingEquipmentFactory)
    assigned_at = factory.LazyFunction(timezone.now)


LabEquipmentFactory = LabEquipmentAssignmentFactory


class RemoteComputerActivityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ComputingActivity

    computing = factory.SubFactory(ComputingEquipmentFactory)
    status = ComputingActivityStatus.FREE

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        if "computer" in kwargs:
            kwargs["computing"] = kwargs.pop("computer")
        return super()._create(model_class, *args, **kwargs)


class LabMonitoringFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MonitoringEvent

    computer = factory.SubFactory(ComputingEquipmentFactory)
    occurred_at = factory.LazyFunction(timezone.now)
    reported_at = factory.LazyFunction(timezone.now)
    agent_id = "agent-test-01"
    event_id = factory.LazyFunction(uuid.uuid4)
    action = "heartbeat"
    action_name = "heartbeat"
    subject_type = "system"
    subject_id = "test-subject"
    subject_name = "test-name"
    payload = factory.LazyFunction(dict)

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        bench = kwargs.pop("bench", None) or kwargs.pop("lab", None)
        if bench is not None:
            computer = kwargs.get("computer")
            if not computer:
                computer = ComputingEquipmentFactory()
                kwargs["computer"] = computer
            EquipmentAssignment.objects.get_or_create(
                bench=bench,
                equipment=computer,
                defaults={"assigned_at": timezone.now()},
            )
        return super()._create(model_class, *args, **kwargs)


__all__ = [
    "ActiveLaboratoryObservationFactory",
    "ActiveUserObservationFactory",
    "BenchBookingFactory",
    "BenchFactory",
    "BenchFavoriteFactory",
    "BenchGroupFactory",
    "BookingVolumeObservationFactory",
    "ComputingEquipmentFactory",
    "EquipmentCategoryFactory",
    "EquipmentKindFactory",
    "EquipmentStatusRecordFactory",
    "LabComputerFactory",
    "LabEquipmentFactory",
    "LabMonitoringFactory",
    "LabProjectFactory",
    "LabSessionLogFactory",
    "LaboratoryVisitEventFactory",
    "MonitoringEventFactory",
    "ProjectUsageObservationFactory",
    "RemoteComputerActivityFactory",
    "StorageQuotaMeasurementFactory",
    "TechnicalUserFactory",
    "UserFactory",
    "VisitorVolumeObservationFactory",
]
