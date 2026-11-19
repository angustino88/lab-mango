"""Daily license warnings (expiry, missing expected licenses) and run-history retention."""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.license_checks.application.alerts import send_missing_license_alerts
from core.labs.features.license_checks.application.retention import purge_license_check_runs
from core.labs.features.licenses.application.status import ChangeLicenseStatusInput, change_license_status
from core.labs.features.licenses.public import send_license_expiry_alerts
from core.labs.models import License, LicenseCheck, LicenseCheckRun, LicenseObservation
from core.labs.models.resource.license.license import LicenseCategory, LicenseProduct, LicenseType, LicenseVendor
from core.users.models import User
from core.websocket.models import Notification
from tests.factories import ComputingEquipmentFactory, grant_labs_role

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return User.objects.create_user(username="license-owner")


@pytest.fixture
def make_license(owner):
    vendor = LicenseVendor.objects.create(name="Vector")
    refs = {
        "product": LicenseProduct.objects.create(name="CANalyzer", vendor=vendor),
        "vendor": vendor,
        "type": LicenseType.objects.create(name="Device locked"),
        "category": LicenseCategory.objects.create(name="Software"),
    }

    def build(sku, expires_in_days=None, **extra):
        expiry = timezone.now() + timedelta(days=expires_in_days) if expires_in_days is not None else None
        return License.objects.create(sku=sku, name=sku, expiry_date=expiry, owner=owner, **refs, **extra)

    return build


def messages(user):
    return sorted(Notification.objects.filter(target_user=user).values_list("message", flat=True))


def test_expiry_warnings_once_per_threshold(owner, make_license):
    make_license("LIC-FAR", 90)
    make_license("LIC-30", 20)
    make_license("LIC-7", 3)
    make_license("LIC-GONE", -2)
    make_license("LIC-OLD", -40)
    revoked = make_license("LIC-REVOKED", 5)
    change_license_status(ChangeLicenseStatusInput(revoked.pk, "revoked"), actor=None)

    result = send_license_expiry_alerts()

    assert result.sent == 3
    assert messages(owner) == [
        "License expired: LIC-GONE",
        "License expires in 19 days: LIC-30",
        "License expires in 2 days: LIC-7",
    ]
    assert send_license_expiry_alerts().sent == 0  # never twice

    assert send_license_expiry_alerts(now=timezone.now() + timedelta(days=4)).sent == 1  # LIC-7 expired
    assert send_license_expiry_alerts(now=timezone.now() + timedelta(days=14)).sent == 1  # LIC-30 at 7 days


def test_renewed_license_warns_again(owner, make_license):
    license_record = make_license("LIC-RENEW", 5)
    send_license_expiry_alerts()
    License.objects.filter(pk=license_record.pk).update(expiry_date=timezone.now() + timedelta(days=25))
    assert send_license_expiry_alerts().sent == 1


def _check_with_run(owner, computer, *expected):
    check = LicenseCheck.objects.create(
        key=f"c{uuid.uuid4().hex[:6]}", name="Vector", probe={}, extract={}, carrier={}
    )
    LicenseCheck.objects.filter(pk=check.pk).update(creator=owner)
    check.refresh_from_db()
    check.expected_licenses.set(expected)
    run = LicenseCheckRun.objects.create(
        license_check=check,
        computing=computer,
        agent_uid=uuid.uuid4(),
        idempotency_key=uuid.uuid4(),
        content_hash="x",
        revision=1,
        sequence=1,
        status="ok",
        started_at=timezone.now(),
        is_applied=True,
        received_at=timezone.now(),
    )
    return check, run


def _observe(check, run, computer, license_record):
    now = timezone.now()
    return LicenseObservation.objects.create(
        license_check=check,
        computing=computer,
        observation_key=f"k-{license_record.pk}",
        product_name=license_record.name,
        carrier_type="computer",
        license=license_record,
        status="matched",
        last_run=run,
        first_seen_at=now,
        last_seen_at=now,
    )


def test_missing_expected_license_warns_once_and_again_after_it_returns(owner, make_license):
    computer = ComputingEquipmentFactory()
    found, missing = make_license("LIC-FOUND"), make_license("LIC-MISSING")
    check, run = _check_with_run(owner, computer, found, missing)
    _observe(check, run, computer, found)

    assert send_missing_license_alerts() == 1
    assert messages(owner) == ["License not found: LIC-MISSING"]
    assert send_missing_license_alerts() == 0

    observation = _observe(check, run, computer, missing)
    assert send_missing_license_alerts() == 0
    observation.removed_at = timezone.now()
    observation.save()
    assert send_missing_license_alerts() == 1


def test_expected_licenses_through_the_api(owner, make_license):
    admin = User.objects.create_user(username="license-api-coord")
    grant_labs_role(admin, "coord")
    client = APIClient()
    client.force_authenticate(admin)
    computer = ComputingEquipmentFactory()
    found, missing = make_license("LIC-A"), make_license("LIC-B")
    check, run = _check_with_run(owner, computer)
    _observe(check, run, computer, found)

    response = client.patch(
        f"/api/labs/license-checks/{check.pk}", {"expected_license_ids": [found.pk, missing.pk]}, format="json"
    )
    assert response.status_code == 200, response.data
    data = response.data["data"]
    assert [(item["name"], item["is_found"]) for item in data["expected_licenses"]] == [
        ("LIC-A", True),
        ("LIC-B", False),
    ]
    assert data["revision"] == 1  # agents do not receive expected licenses
    bad = client.patch(f"/api/labs/license-checks/{check.pk}", {"expected_license_ids": [999999]}, format="json")
    assert bad.status_code == 422


def test_old_runs_are_purged_but_current_ones_kept(owner):
    computer = ComputingEquipmentFactory()
    check, newest = _check_with_run(owner, computer)
    old = timezone.now() - timedelta(days=40)

    def run(sequence):
        return LicenseCheckRun.objects.create(
            license_check=check,
            computing=computer,
            agent_uid=uuid.uuid4(),
            idempotency_key=uuid.uuid4(),
            content_hash="x",
            revision=1,
            sequence=sequence,
            status="failed",
            started_at=old,
            received_at=old,
        )

    referenced, stale = run(0), run(0)
    LicenseCheckRun.objects.filter(pk=newest.pk).update(sequence=5, received_at=old)
    now = timezone.now()
    LicenseObservation.objects.create(
        license_check=check,
        computing=computer,
        observation_key="k",
        product_name="P",
        carrier_type="computer",
        status="unregistered",
        last_run=referenced,
        first_seen_at=now,
        last_seen_at=now,
    )

    assert purge_license_check_runs() == 1
    assert set(LicenseCheckRun.objects.values_list("pk", flat=True)) == {newest.pk, referenced.pk}
    assert not LicenseCheckRun.objects.filter(pk=stale.pk).exists()
