"""Unit tests for analytics Celery tasks — mock-based, no real DB access."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

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
        content = generate_ical("testuser", "example.com").decode("utf-8")
        assert "@bosch.com" not in content


# ---------------------------------------------------------------------------
# snapshot_daily_facility_visitors
# ---------------------------------------------------------------------------


class TestCountVisitDailyTask:
    def test_creates_observation_with_visitor_count(self):
        mock_qs = MagicMock()
        mock_qs.values.return_value.distinct.return_value.count.return_value = 7
        with (
            patch(f"{_TASKS_MODULE}.LaboratoryVisitEvent") as MockVisitLog,
            patch(f"{_TASKS_MODULE}.VisitorVolumeObservation") as MockObservation,
        ):
            MockVisitLog.objects.filter.return_value = mock_qs

            count_visit_daily()

            MockObservation.objects.update_or_create.assert_called_once()
            assert MockObservation.objects.update_or_create.call_args.kwargs["defaults"]["distinct_visitor_count"] == 7

    def test_returns_none(self):
        mock_qs = MagicMock()
        mock_qs.values.return_value.distinct.return_value.count.return_value = 0
        with (
            patch(f"{_TASKS_MODULE}.LaboratoryVisitEvent") as MockVisitLog,
            patch(f"{_TASKS_MODULE}.VisitorVolumeObservation"),
        ):
            MockVisitLog.objects.filter.return_value = mock_qs
            result = count_visit_daily()
        assert result is None

    def test_filters_within_current_day(self):
        mock_qs = MagicMock()
        mock_qs.values.return_value.distinct.return_value.count.return_value = 0
        with (
            patch(f"{_TASKS_MODULE}.LaboratoryVisitEvent") as MockVisitLog,
            patch(f"{_TASKS_MODULE}.VisitorVolumeObservation"),
        ):
            MockVisitLog.objects.filter.return_value = mock_qs
            count_visit_daily()
            call_kwargs = MockVisitLog.objects.filter.call_args.kwargs
            assert "occurred_at__gte" in call_kwargs
            assert "occurred_at__lt" in call_kwargs


# ---------------------------------------------------------------------------
# snapshot_daily_booking_volume
# ---------------------------------------------------------------------------


class TestCountBookingDailyTask:
    def test_creates_observation_with_booking_count(self):
        mock_qs = MagicMock()
        mock_qs.count.return_value = 3
        with (
            patch(f"{_TASKS_MODULE}.BenchBooking") as MockBooking,
            patch(f"{_TASKS_MODULE}.BookingVolumeObservation") as MockObservation,
        ):
            MockBooking.objects.filter.return_value = mock_qs

            count_booking_daily()

            MockObservation.objects.update_or_create.assert_called_once()
            assert MockObservation.objects.update_or_create.call_args.kwargs["defaults"]["booking_count"] == 3

    def test_filters_within_current_day(self):
        mock_qs = MagicMock()
        mock_qs.count.return_value = 0
        with (
            patch(f"{_TASKS_MODULE}.BenchBooking") as MockBooking,
            patch(f"{_TASKS_MODULE}.BookingVolumeObservation"),
        ):
            MockBooking.objects.filter.return_value = mock_qs
            count_booking_daily()
            call_kwargs = MockBooking.objects.filter.call_args.kwargs
            assert "created__gte" in call_kwargs
            assert "created__lt" in call_kwargs


# ---------------------------------------------------------------------------
# snapshot_daily_active_users
# ---------------------------------------------------------------------------


class TestCountTotalUserDailyTask:
    def test_creates_observation_with_active_user_count(self):
        with (
            patch("core.users.models.User") as MockUser,
            patch(f"{_TASKS_MODULE}.ActiveUserObservation") as MockObservation,
        ):
            MockUser.objects.filter.return_value.count.return_value = 42

            count_total_user_daily()

            MockObservation.objects.update_or_create.assert_called_once()
            assert MockObservation.objects.update_or_create.call_args.kwargs["defaults"]["active_user_count"] == 42

    def test_filters_only_active_users(self):
        with (
            patch("core.users.models.User") as MockUser,
            patch(f"{_TASKS_MODULE}.ActiveUserObservation"),
        ):
            MockUser.objects.filter.return_value.count.return_value = 0
            count_total_user_daily()
            MockUser.objects.filter.assert_called_once_with(is_active=True)


# ---------------------------------------------------------------------------
# snapshot_daily_active_benches
# ---------------------------------------------------------------------------


class TestCountTotalLabDailyTask:
    def test_creates_observation_with_active_lab_count(self):
        with (
            patch(f"{_TASKS_MODULE}.Bench") as MockLab,
            patch(f"{_TASKS_MODULE}.ActiveLaboratoryObservation") as MockObservation,
        ):
            MockLab.objects.filter.return_value.count.return_value = 15

            count_total_lab_daily()

            MockObservation.objects.update_or_create.assert_called_once()
            assert MockObservation.objects.update_or_create.call_args.kwargs["defaults"]["active_laboratory_count"] == 15

    def test_filters_by_deleted_at_isnull(self):
        with (
            patch(f"{_TASKS_MODULE}.Bench") as MockLab,
            patch(f"{_TASKS_MODULE}.ActiveLaboratoryObservation"),
        ):
            MockLab.objects.filter.return_value.count.return_value = 0
            count_total_lab_daily()
            MockLab.objects.filter.assert_called_once_with(deleted_at__isnull=True)


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
