"""Storage utilization is ranked fullest first; a top-N cut keeps the fullest accounts."""

from datetime import datetime, timezone

import pytest

from core.labs.features.analytics.queries.storage import list_storage_quota_measurements
from tests.factories import StorageQuotaMeasurementFactory

pytestmark = pytest.mark.django_db

DAY = datetime(2026, 11, 10, tzinfo=timezone.utc)


def _measure(account: str, used: float):
    return StorageQuotaMeasurementFactory(
        account_identifier=account,
        used_gibibytes=used,
        quota_gibibytes=100,
        measured_at=datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc),
    )


def test_top_n_keeps_the_fullest_accounts_in_descending_order():
    for account, used in (("a", 20), ("b", 95), ("c", 82), ("d", 55), ("e", 40)):
        _measure(account, used)

    rows = list_storage_quota_measurements(log_date=DAY, top_n=3)

    assert [row["account_identifier"] for row in rows] == ["b", "c", "d"]
