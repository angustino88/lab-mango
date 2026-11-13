"""Tests for analytics Celery tasks: snapshots use the database, alert dispatch is mock-based."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from django.utils import timezone

from core.labs.features.analytics.application.notifications import generate_storage_quota_ical as generate_ical
from core.labs.features.analytics.application.tasks import (
    send_storage_quota_alerts as email_user_exceed_storage_quota,
)
from core.labs.features.analytics.application.tasks import (
    snapshot_daily_active_benches as count_total_lab_daily,
)
from core.labs.features.analytics.application.tasks import (
    snapshot_daily_active_users as count_total_user_daily,
)
from core.labs.features.analytics.application.tasks import (
    snapshot_daily_booking_volume as count_booking_daily,
)
from core.labs.features.analytics.application.tasks import (
    snapshot_daily_facility_visitors as count_visit_daily,
)
from core.labs.models import (
    ActiveLaboratoryObservation,
    ActiveUserObservation,
    AnalyticsGranularity,
    AnalyticsSource,
    BenchBooking,
    BookingVolumeObservation,
    VisitorVolumeObservation,
)
from core.users.models import User
from tests.factories import BenchBookingFactory, BenchFactory, LaboratoryVisitEventFactory, UserFactory

_TASKS_MODULE = "core.labs.features.analytics.application.tasks"

# ---------------------------------------------------------------------------
# generate_ical
# ---------------------------------------------------------------------------


class TestGenerateIcal:
    def test_returns_bytes(self):
        result = generate_ical("testuser", "example.com")
        assert isinstance(result, bytes)

    def test_valid_ical_structure(self):
        content = generate_ical("testuser", "example.com").decode("utf-8")
        assert "BEGIN:VCALENDAR" in content
        assert "END:VCALENDAR" in content
        assert "BEGIN:VEVENT" in content
        assert "END:VEVENT" in content

    def test_each_field_on_separate_crlf_line(self):
        """Verify every field is its own CRLF-terminated line."""
        content = generate_ical("testuser", "example.com").decode("utf-8")
        lines = content.split("\r\n")

        created_lines = [ln for ln in lines if ln.startswith("CREATED:")]
        summary_lines = [ln for ln in lines if ln.startswith("SUMMARY:")]
        description_lines = [ln for ln in lines if ln.startswith("DESCRIPTION:")]
        organizer_lines = [ln for ln in lines if ln.startswith("ORGANIZER:")]

        assert len(created_lines) == 1
        assert len(summary_lines) == 1
        assert len(description_lines) == 1
        assert len(organizer_lines) == 1

    def test_uses_provided_email_domain(self):
        content = generate_ical("john", "mycompany.com").decode("utf-8")
        assert "john@mycompany.com" in content

    def test_uses_crlf_line_endings(self):
        content = generate_ical("testuser", "example.com").decode("utf-8")
        assert "\r\n" in content

    def test_no_hardcoded_domain(self):
        # The organizer comes from DEFAULT_FROM_EMAIL (environment-specific); pin it so the
        # test checks only that no domain is hard-coded in the generator itself.
        with override_settings(DEFAULT_FROM_EMAIL="noreply@example.org"):
            content = generate_ical("testuser", "example.com").decode("utf-8")
        assert "@bosch.com" not in content
        assert "ATTENDEE:mailto:testuser@example.com" in content


# ---------------------------------------------------------------------------
# Daily snapshots (real database: they record the local day that just ended)
# ---------------------------------------------------------------------------


def _day_start(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min))


@pytest.fixture
def yesterday() -> date:
    return timezone.localdate() - timedelta(days=1)


@pytest.mark.django_db
class TestDailySnapshots:
    def test_booking_volume_counts_bookings_created_yesterday_only(self, yesterday):
        bookings = BenchBookingFactory.create_batch(3)
        BenchBooking.objects.filter(pk__in=[b.pk for b in bookings[:2]]).update(
            created=_day_start(yesterday) + timedelta(hours=10)
        )
        BenchBooking.objects.filter(pk=bookings[2].pk).update(created=_day_start(yesterday) - timedelta(seconds=1))

        assert count_booking_daily() is None

        row = BookingVolumeObservation.objects.get()
        assert (row.period_start, row.period_end) == (
            _day_start(yesterday),
            _day_start(yesterday + timedelta(days=1)),
        )
        assert (row.granularity, row.source, row.booking_count) == (
            AnalyticsGranularity.DAILY,
            AnalyticsSource.APPLICATION,
            2,
        )

    def test_booking_volume_accepts_an_explicit_day_for_backfill(self):
        day = timezone.localdate() - timedelta(days=10)
        booking = BenchBookingFactory()
        BenchBooking.objects.filter(pk=booking.pk).update(created=_day_start(day) + timedelta(hours=1))

        count_booking_daily(day.isoformat())

        row = BookingVolumeObservation.objects.get()
        assert (row.period_start, row.booking_count) == (_day_start(day), 1)

    def test_visitors_counts_distinct_visitors(self, yesterday):
        visitor = UserFactory()
        at = _day_start(yesterday) + timedelta(hours=9)
        LaboratoryVisitEventFactory(visitor=visitor, occurred_at=at)
        LaboratoryVisitEventFactory(visitor=visitor, occurred_at=at + timedelta(hours=1))
        LaboratoryVisitEventFactory(visitor=UserFactory(), occurred_at=at)
        LaboratoryVisitEventFactory(visitor=UserFactory(), occurred_at=_day_start(yesterday) - timedelta(minutes=1))

        count_visit_daily()

        assert VisitorVolumeObservation.objects.get().distinct_visitor_count == 2

    def test_active_users_counts_only_active_accounts(self, yesterday):
        active_before = User.objects.filter(is_active=True).count()
        UserFactory(is_active=True)
        UserFactory(is_active=False)

        count_total_user_daily()

        row = ActiveUserObservation.objects.get()
        assert (row.period_start, row.active_user_count) == (_day_start(yesterday), active_before + 1)

    def test_active_benches_excludes_deleted(self, yesterday):
        BenchFactory()
        BenchFactory(deleted_at=timezone.now())

        count_total_lab_daily()

        row = ActiveLaboratoryObservation.objects.get()
        assert (row.period_start, row.active_laboratory_count) == (_day_start(yesterday), 1)

    def test_rerun_overwrites_the_same_row(self, yesterday):
        count_booking_daily()
        booking = BenchBookingFactory()
        BenchBooking.objects.filter(pk=booking.pk).update(created=_day_start(yesterday) + timedelta(hours=1))

        count_booking_daily()

        assert BookingVolumeObservation.objects.get().booking_count == 1


# ---------------------------------------------------------------------------
# send_storage_quota_alerts
# ---------------------------------------------------------------------------


class TestEmailUserExceedStorageQuotaTask:
    def test_returns_true_when_no_exceeded_quotas(self):
        with patch(f"{_TASKS_MODULE}.StorageQuotaMeasurement") as MockMeasurement:
            MockMeasurement.objects.filter.return_value = []
            result = email_user_exceed_storage_quota()
        assert result is True

    def test_sends_per_user_and_management_emails(self):
        quota1 = MagicMock()
        quota1.account_identifier = "alice"
        quota2 = MagicMock()
        quota2.account_identifier = "bob"

        with (
            patch(f"{_TASKS_MODULE}.StorageQuotaMeasurement") as MockMeasurement,
            patch(f"{_TASKS_MODULE}.send_storage_quota_user_email", return_value=True) as mock_user_email,
            patch(f"{_TASKS_MODULE}.send_storage_quota_management_email", return_value=True) as mock_mgmt_email,
            patch(f"{_TASKS_MODULE}.LabManagementEmail") as MockMgmtEmail,
        ):
            MockMeasurement.objects.filter.return_value = [quota1, quota2]
            MockMgmtEmail.objects.filter.return_value.values_list.return_value = []
            result = email_user_exceed_storage_quota()

        assert result is True
        assert mock_user_email.call_count == 2
        mock_mgmt_email.assert_called_once()

    def test_returns_false_when_user_email_helper_returns_false(self):
        quota = MagicMock()
        quota.account_identifier = "alice"

        with (
            patch(f"{_TASKS_MODULE}.StorageQuotaMeasurement") as MockMeasurement,
            patch(f"{_TASKS_MODULE}.send_storage_quota_user_email", return_value=False),
            patch(f"{_TASKS_MODULE}.send_storage_quota_management_email", return_value=True),
            patch(f"{_TASKS_MODULE}.LabManagementEmail") as MockMgmtEmail,
        ):
            MockMeasurement.objects.filter.return_value = [quota]
            MockMgmtEmail.objects.filter.return_value.values_list.return_value = []
            result = email_user_exceed_storage_quota()

        assert result is False

    def test_returns_false_when_one_user_email_fails(self):
        quota1 = MagicMock()
        quota1.account_identifier = "alice"
        quota2 = MagicMock()
        quota2.account_identifier = "bob"

        with (
            patch(f"{_TASKS_MODULE}.StorageQuotaMeasurement") as MockMeasurement,
            patch(f"{_TASKS_MODULE}.send_storage_quota_user_email", side_effect=[True, False]),
            patch(f"{_TASKS_MODULE}.send_storage_quota_management_email", return_value=True),
            patch(f"{_TASKS_MODULE}.LabManagementEmail") as MockMgmtEmail,
        ):
            MockMeasurement.objects.filter.return_value = [quota1, quota2]
            MockMgmtEmail.objects.filter.return_value.values_list.return_value = []
            result = email_user_exceed_storage_quota()

        assert result is False

    def test_returns_false_when_management_email_fails(self):
        quota = MagicMock()
        quota.account_identifier = "alice"

        with (
            patch(f"{_TASKS_MODULE}.StorageQuotaMeasurement") as MockMeasurement,
            patch(f"{_TASKS_MODULE}.send_storage_quota_user_email", return_value=True),
            patch(f"{_TASKS_MODULE}.send_storage_quota_management_email", return_value=False),
            patch(f"{_TASKS_MODULE}.LabManagementEmail") as MockMgmtEmail,
        ):
            MockMeasurement.objects.filter.return_value = [quota]
            MockMgmtEmail.objects.filter.return_value.values_list.return_value = []
            result = email_user_exceed_storage_quota()

        assert result is False

    def test_groups_multiple_quotas_per_user(self):
        quota1 = MagicMock()
        quota1.account_identifier = "alice"
        quota2 = MagicMock()
        quota2.account_identifier = "alice"

        with (
            patch(f"{_TASKS_MODULE}.StorageQuotaMeasurement") as MockMeasurement,
            patch(f"{_TASKS_MODULE}.send_storage_quota_user_email", return_value=True) as mock_user_email,
            patch(f"{_TASKS_MODULE}.send_storage_quota_management_email", return_value=True),
            patch(f"{_TASKS_MODULE}.LabManagementEmail") as MockMgmtEmail,
        ):
            MockMeasurement.objects.filter.return_value = [quota1, quota2]
            MockMgmtEmail.objects.filter.return_value.values_list.return_value = []
            email_user_exceed_storage_quota()

        assert mock_user_email.call_count == 1
        called_quotas = mock_user_email.call_args[0][1]
        assert len(called_quotas) == 2
